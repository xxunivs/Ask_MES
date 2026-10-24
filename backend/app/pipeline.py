"""질문 -> SQL -> 결과 (웹 API, 벤치마크 공용)

1. 관련 테이블 찾기   개념 사전 + 벡터 검색          retrieval/
2. JOIN 경로 계산     FK 그래프 최단 경로            retrieval/
3. 실제 값 확인       찾은 컬럼의 값 분포, 샘플 행   sampling/
4. SQL 생성           프롬프트 + LLM                 generation/
5. 자동 교정          확정적인 문법 오류 수정        autofix/
6. 검증               스키마, 코드값, 안전성         validation/
7. 실행               DB 실행                        execution/
검증이나 실행에서 실패하면 오류를 넣어 1회씩 재생성
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.autofix.sql_autofix import autofix_sql
from app.execution.sql_executor import execute_sql
from app.generation.llm import llm_generate
from app.generation.prompts import PreviousAttempt, build_prompt, parse_llm_json
from app.retrieval.retriever import RetrievalConfig, retrieve_context
from app.sampling.live_sample import build_live_db_context
from app.validation.query_safety import validate_query
from app.validation.sql_validator import validate_sql

GENERATE_MAX_TOKENS = 512


@dataclass
class PipelineResult:
    question: str
    sql: str = ""
    schema_valid: bool = False
    schema_error: str = ""
    executed: bool = False
    data: dict | None = None
    db_error: str = ""
    trace: list[dict[str, str]] = field(default_factory=list)

    def log(self, step: str, detail: str) -> None:
        self.trace.append({"step": step, "detail": detail})


async def run_pipeline(
    question: str,
    *,
    preset: str = "FULL",
    top_k: int | None = None,
    limit: int = 100,
    execute: bool = True,
) -> PipelineResult:
    result = PipelineResult(question=question)

    schema_ctx = retrieve_context(question, n=top_k, config=RetrievalConfig.from_preset(preset))
    for step, detail in _split_schema_context(schema_ctx):
        result.log(step, detail)

    try:
        db_ctx = await build_live_db_context(schema_ctx)
    except Exception as e:
        db_ctx = ""
        result.log("3. 실제 값 확인", f"조회 실패: {e}")
    else:
        result.log("3. 실제 값 확인", db_ctx or "(값 없음)")

    previous: PreviousAttempt | None = None
    for tag in (" (시도 1)", " (시도 2)"):
        sql = await _generate(build_prompt(question, schema_ctx, db_ctx, previous), result, tag)
        error = _check(sql, question)
        result.sql, result.schema_valid, result.schema_error = sql, not error, error
        result.log("6. 검증" + tag, error or "통과")
        if not error:
            break
        previous = PreviousAttempt(sql, error, "validation")

    if not execute or not result.schema_valid:
        return result

    await _execute(result, limit, "7. 실행")
    if not result.executed:
        tag = " (DB 오류 교정)"
        previous = PreviousAttempt(result.sql, result.db_error, "db")
        retry_sql = await _generate(build_prompt(question, schema_ctx, db_ctx, previous), result, tag)
        if retry_sql and not _check(retry_sql, question):
            result.sql = retry_sql
            await _execute(result, limit, "7. 실행" + tag)
    return result


async def _generate(prompt: str, result: PipelineResult, tag: str) -> str:
    result.log("4. LLM 프롬프트" + tag, prompt)
    raw = await llm_generate(prompt, temperature=0.05, max_tokens=GENERATE_MAX_TOKENS)
    result.log("4. LLM 응답" + tag, raw)
    sql, fixes = autofix_sql((parse_llm_json(raw).get("sql") or "").strip())
    result.log("5. 자동 교정" + tag, "\n".join(fixes) or "교정 없음")
    return sql


def _check(sql: str, question: str) -> str:
    vr = validate_sql(sql, question=question)
    if not vr.ok:
        return vr.error_message()
    safety = validate_query(sql)
    return "" if safety.ok else f"[SafetyLayer] {safety.error_message()}"


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
    labels = {"## 개념 매핑": "1. 관련 테이블 찾기 (개념 사전)", "## JOIN 경로 힌트": "2. JOIN 경로 계산"}
    parts = re.split(r"\n\s*(?=## )", schema_ctx)
    steps = [("1. 관련 테이블 찾기 (벡터 검색)", parts[0].strip())]
    for part in parts[1:]:
        title = next((v for k, v in labels.items() if part.startswith(k)), part.split("\n", 1)[0])
        steps.append((title, part.split("\n", 1)[1].strip() if "\n" in part else ""))
    return steps
