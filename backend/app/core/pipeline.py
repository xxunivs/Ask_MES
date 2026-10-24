"""
자연어 질문 -> SQL -> 실행 결과 파이프라인

웹 API(/chat/nl-to-sql)와 벤치마크(eval/run_benchmark.py)가 같은 함수를 쓴다.

  1. 관련 테이블 찾기   개념 사전 + 벡터 검색        retriever.retrieve_context
  2. JOIN 경로 계산     FK 그래프 최단 경로          retriever.retrieve_context
  3. 실제 값 확인       테이블별 샘플 조회           live_sample.build_live_db_context
  4. SQL 생성           프롬프트 조립 + LLM          prompts, llm
  5. 자동 교정          확정적인 문법 오류 수정      sql_autofix.autofix_sql
  6. 검증               스키마, 코드값, 안전성       sql_validator, query_safety
                        실패 시 오류를 넣어 1회 재생성
  7. 실행               DB 실행                      sql_executor.execute_sql
                        실패 시 DB 오류를 넣어 1회 재생성
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.live_sample import build_live_db_context
from app.core.llm import llm_generate
from app.core.prompts import (
    NL_TO_SQL_PROMPT,
    build_db_correction_prompt,
    build_schema_correction_prompt,
    parse_llm_json,
    static_prompt_hints,
)
from app.core.query_safety import validate_query
from app.core.retriever import RetrievalConfig, retrieve_context
from app.core.sql_autofix import autofix_sql
from app.core.sql_executor import execute_sql
from app.core.sql_validator import validate_sql

# 검증 실패 시 재생성 횟수, DB 실행 실패 시 재생성 횟수
SCHEMA_RETRY_MAX = 1
DB_RETRY_MAX = 1
GENERATE_MAX_TOKENS = 512


@dataclass
class PipelineResult:
    question: str
    sql: str = ""
    schema_valid: bool = False
    schema_error: str = ""
    executed: bool = False
    data: Optional[dict] = None
    db_error: str = ""
    # 단계별 중간 결과 [{step, detail}]
    trace: list[dict[str, str]] = field(default_factory=list)

    def log(self, step: str, detail: str) -> None:
        self.trace.append({"step": step, "detail": detail})


async def run_pipeline(
    question: str,
    *,
    preset: str = "FULL",
    top_k: Optional[int] = None,
    limit: int = 100,
    execute: bool = True,
) -> PipelineResult:
    """질문 하나를 SQL 로 바꾸고 실행. preset 은 검색 구성(B0~FULL, ablation 용)"""
    result = PipelineResult(question=question)

    # 1~2. 관련 테이블 찾기, JOIN 경로 계산
    schema_ctx = retrieve_context(question, n=top_k, config=RetrievalConfig.from_preset(preset))
    for step, detail in _split_schema_context(schema_ctx):
        result.log(step, detail)

    # 3. 실제 값 확인
    try:
        db_ctx = await build_live_db_context(schema_ctx)
    except Exception as e:
        db_ctx = "(DB 샘플 조회 실패)"
        print(f"[DBContext] 오류: {e}")
    result.log("3. 실제 값 확인", db_ctx or "(샘플 없음)")

    # 4~6. SQL 생성, 자동 교정, 검증 (실패 시 오류를 넣어 재생성)
    prompt = NL_TO_SQL_PROMPT.format(schema=schema_ctx, db_context=db_ctx, question=question, **static_prompt_hints())
    for attempt in range(SCHEMA_RETRY_MAX + 1):
        tag = f" (시도 {attempt + 1})"
        result.log("4. LLM 프롬프트" + tag, prompt)
        sql = await _generate_sql(prompt, result, tag)
        sql = _autofix(sql, result, tag)
        vr = validate_sql(sql, question=question)
        result.sql, result.schema_valid, result.schema_error = sql, vr.ok, vr.error_message()
        if vr.ok:
            safety = validate_query(sql)
            if safety.ok:
                result.log("6. 검증" + tag, "통과")
                break
            result.schema_valid, result.schema_error = False, f"[SafetyLayer] {safety.error_message()}"
        result.log("6. 검증" + tag, result.schema_error)
        if attempt < SCHEMA_RETRY_MAX:
            prompt = build_schema_correction_prompt(question, schema_ctx, sql, vr)

    if not execute or not result.schema_valid:
        return result

    # 7. 실행 (실패 시 DB 오류를 넣어 재생성)
    await _execute(result, limit, "7. 실행")
    for _ in range(DB_RETRY_MAX):
        if result.executed:
            break
        prompt = build_db_correction_prompt(question, schema_ctx, result.sql, result.db_error)
        retry_sql = _autofix(await _generate_sql(prompt, result, " (DB 오류 교정)"), result, " (DB 오류 교정)")
        if not retry_sql or not validate_sql(retry_sql, question=question).ok or not validate_query(retry_sql).ok:
            break
        result.sql = retry_sql
        await _execute(result, limit, "7. 실행 (DB 오류 교정)")
    return result


async def _generate_sql(prompt: str, result: PipelineResult, tag: str) -> str:
    raw = await llm_generate(prompt, temperature=0.05, max_tokens=GENERATE_MAX_TOKENS)
    result.log("4. LLM 응답" + tag, raw)
    return (parse_llm_json(raw).get("sql") or "").strip()


def _autofix(sql: str, result: PipelineResult, tag: str) -> str:
    fixed, fixes = autofix_sql(sql)
    result.log("5. 자동 교정" + tag, "\n".join(fixes) if fixes else "교정 없음")
    return fixed


async def _execute(result: PipelineResult, limit: int, step: str) -> None:
    try:
        res = await execute_sql(result.sql, limit=limit)
    except Exception as e:
        result.executed, result.data, result.db_error = False, None, str(e)
        result.log(step, f"DB 오류: {e}")
        return
    result.executed, result.db_error = True, ""
    result.data = {"columns": res.get("columns", []), "rows": res.get("rows", []), "count": res.get("count", 0)}
    result.log(step, f"{result.data['count']}행 반환")


def _split_schema_context(schema_ctx: str) -> list[tuple[str, str]]:
    """retrieve_context 결과를 단계별 기록용으로 분리"""
    labels = {"## 개념 매핑": "1. 관련 테이블 찾기 (개념 사전)", "## JOIN 경로 힌트": "2. JOIN 경로 계산"}
    parts = re.split(r"\n\s*(?=## )", schema_ctx)
    steps = [("1. 관련 테이블 찾기 (벡터 검색)", parts[0].strip())]
    for part in parts[1:]:
        title = next((v for k, v in labels.items() if part.startswith(k)), part.split("\n", 1)[0])
        steps.append((title, part.split("\n", 1)[1].strip() if "\n" in part else ""))
    return steps
