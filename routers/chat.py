"""
/chat 라우터
  POST /chat/nl-to-sql   : 자연어 → SQL 생성 + DB 실행
  POST /chat/analyze     : 조회된 데이터에 대한 분석 질문
  GET  /chat/health      : LLM 연결 상태 확인
"""
from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Any

from core.ollama import llm_generate, check_ollama
from core.config import LLM_MODEL, LLM_PROVIDER
from core.retriever import retrieve_context
from core.db_client import execute_sql
from core.db_context import build_live_db_context, validate_sql_against_schema
from core.term_resolver import (
    align_sql_with_live_candidates,
    detect_ambiguous_terms,
    finalize_term_resolution,
    format_term_resolution_for_prompt,
    format_term_resolution_for_user,
    prepare_term_resolution_context,
)

router = APIRouter()

# ─────────────────────────────────────────────
# 요청/응답 모델
# ─────────────────────────────────────────────

class NlToSqlRequest(BaseModel):
    question: str
    limit: int = 100
    user_role: str = "general"
    current_view: str = "chat"
    conversation_context: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    question: str
    data: Optional[dict] = None  # { columns: [...], rows: [{...}] }


# ─────────────────────────────────────────────
# 프롬프트 템플릿
# ─────────────────────────────────────────────

NL_TO_SQL_PROMPT = """MES 질문을 간결한 MS SQL Server SELECT로 변환하세요.

## 스키마
{schema}

## 실제 DB
{db_context}

## 역할·문맥·모호어 후보
{term_context}

## 규칙
1. SELECT만 생성하고 모든 테이블에 WITH (NOLOCK)을 사용합니다.
2. 제공된 실제 테이블·컬럼·JOIN만 사용합니다.
3. 모호어는 역할·대화·실데이터를 함께 판단합니다. 반드시 아래 후보 중 값있음 후보를 SQL에 사용하고 후보 밖의 유사 컬럼은 쓰지 않습니다.
4. 날짜 미지정/상대 날짜의 기준은 1년 전 GETDATE()이며, 명시 날짜는 리터럴을 사용합니다. 범위는 >=, <로 작성합니다.
5. 생산량은 CIM_LOT.QTY 합계, 생산건수는 COUNT(*), 일별 추이는 CONVERT(date,...), 설비 추이는 CIM_LOT.TRACKINTIME/EQUIPMENTID를 사용합니다.
6. 비율은 * 100하고 0 나눗셈을 방지합니다. alias에 DATE, TIME, NAME, VALUE, COUNT, STATE, TYPE, DATA, KEY, INDEX, ORDER를 쓰지 않습니다.

7. SELECT 컬럼은 기본 4개 이하, JOIN은 2개 이하로 제한하고 TOP 20 이하의 짧은 SQL을 만듭니다.

첫 글자부터 한 줄 JSON만 응답하고 사고과정·설명·마크다운은 출력하지 마세요:
{{"sql":"SELECT ...","term_choices":{{"모호어":"TABLE.COLUMN"}}}}

## 질문
{question}

JSON 응답:"""


SQL_REPAIR_PROMPT = """아래 SQL을 오류 한 가지만 반영해 간결한 MS SQL Server SELECT로 수정하세요.

## MES 스키마 정보
{schema}

## 실제 MES DB 탐색 결과
{db_context}

## 모호 제조 용어 해석
{term_context}

## 사용자 질문
{question}

## 실패한 SQL
{sql}

## DB 오류
{error}

SELECT만 사용하고 모든 테이블에 WITH (NOLOCK)을 적용하세요. 제공된 스키마에 없는 이름을 만들지 말고 불필요한 컬럼/JOIN을 제거하세요.

첫 글자부터 한 줄 JSON만 응답:
{{"sql":"SELECT ..."}}
"""


ANALYZE_PROMPT = """당신은 MES 데이터 분석 전문가입니다.
다음 데이터를 분석하여 한국어로 명확하고 간결하게 답변하세요.

## 데이터 컬럼
{columns}

## 데이터 샘플 (최대 20행)
{rows}

## 사용자 질문
{question}

분석 결과를 3-5문장으로 요약하세요. 수치 근거를 포함하세요."""


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def _parse_llm_json(raw: str) -> dict[str, Any]:
    """LLM 응답에서 첫 JSON 객체를 추출."""
    # 마크다운 코드블록 제거
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # JSON 블록 추출 시도: 모델이 뒤에 예시를 이어 쓰는 경우가 있어 첫 valid object만 사용
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start():])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    # Fallback: SELECT 구문 직접 추출
    sql_match = re.search(r'(SELECT\s.+?)(?:;|$)', raw, re.DOTALL | re.IGNORECASE)
    sql = sql_match.group(1).strip() if sql_match else raw
    return {"sql": sql, "description": "", "resolved_terms": []}


def _resolved_terms_from_choices(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    choices = parsed.get("term_choices")
    if not isinstance(choices, dict):
        resolved_terms = parsed.get("resolved_terms")
        return resolved_terms if isinstance(resolved_terms, list) else []

    return [
        {
            "term": str(term),
            "selected_columns": [str(column)],
            "confidence": 0.7,
            "evidence": ["역할, 대화 맥락 및 실제 DB 후보를 함께 비교"],
        }
        for term, column in choices.items()
        if term and column
    ]


def _clip_prompt_text(text: str, max_chars: int) -> str:
    """Conservatively keep Korean-heavy prompts below the 2048-token limit."""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... (컨텍스트 길이 제한으로 일부 생략)"


def _sql_contains_column(sql: str, column_ref: str) -> bool:
    match = re.match(r"^\s*(CIM_[A-Z0-9_]+)\.([A-Z0-9_]+)\s*$", column_ref.upper())
    if not match:
        return False
    table, column = match.groups()
    upper_sql = sql.upper()
    return column in upper_sql and table in upper_sql


def _term_resolution_sql_errors(sql: str, term_resolution: dict[str, Any] | None) -> list[str]:
    if not term_resolution or term_resolution.get("mode") != "single_pass_role_context_db_resolution":
        return []

    errors: list[str] = []
    for item in term_resolution.get("resolved_terms", []) or []:
        term = str(item.get("term", ""))
        meaning = str(item.get("selected_meaning", ""))
        columns = item.get("validated_columns") or item.get("selected_columns") or []
        columns = [str(col) for col in columns if isinstance(col, str)]
        if not columns:
            continue

        missing = [col for col in columns[:4] if not _sql_contains_column(sql, col)]
        if missing:
            errors.append(
                f"모호어 '{term}'은 '{meaning}'로 해석됐으므로 SQL에 선택 후보 컬럼 "
                f"{', '.join(missing)} 이 포함되어야 합니다."
            )
    return errors


def _semantic_sql_errors(question: str, sql: str, term_resolution: dict[str, Any] | None = None) -> list[str]:
    """Catch common SQL that runs but answers the wrong MES business question."""
    q = question.replace(" ", "")
    upper_sql = sql.upper()
    errors: list[str] = []

    if "생산" in q:
        if "CIM_LOT" not in upper_sql:
            errors.append("생산량/생산 실적 질문은 CIM_LOT를 기준 테이블로 사용해야 합니다.")
        if "생산량" in q and "SUM(" not in upper_sql:
            errors.append("생산량 질문은 COUNT만 쓰지 말고 CIM_LOT.QTY를 SUM 집계해야 합니다.")
        if "생산량" in q and ".QTY" not in upper_sql and " QTY" not in upper_sql and "[QTY]" not in upper_sql:
            errors.append("생산량 질문에는 CIM_LOT.QTY 컬럼이 포함되어야 합니다.")
    if "설비별" in q and "생산" in q and "EQUIPMENTID" not in upper_sql:
        errors.append("설비별 생산 질문은 EQUIPMENTID 기준으로 그룹화해야 합니다.")
    if "제품별" in q and "생산" in q and "PRODUCTDEFINITIONID" not in upper_sql:
        errors.append("제품별 생산 질문은 PRODUCTDEFINITIONID 기준으로 그룹화해야 합니다.")

    errors.extend(_term_resolution_sql_errors(sql, term_resolution))
    return errors


async def _llm_sql_from_prompt(prompt: str, max_tokens: int = 256) -> tuple[str, str, list[dict[str, Any]]]:
    raw_response = await llm_generate(prompt, temperature=0.05, max_tokens=max_tokens)
    parsed = _parse_llm_json(raw_response)
    sql = str(parsed.get("sql", ""))
    description = str(parsed.get("description", ""))
    resolved_terms = _resolved_terms_from_choices(parsed)
    if not sql:
        print(f"[LLM_SQL_RAW] {raw_response[:800]}")
        raise HTTPException(status_code=500, detail="SQL 생성 실패 — LLM 응답을 파싱할 수 없습니다.")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise HTTPException(status_code=500, detail=f"SQL 생성 실패 — SELECT 문이 아닙니다: {sql[:120]}")
    return sql, description, resolved_terms


def _rows_to_text(columns: list, rows: list, max_rows: int = 20) -> str:
    """rows(dict 배열) → 텍스트 표 변환"""
    if not rows:
        return "(데이터 없음)"
    lines = ["\t".join(str(c) for c in columns)]
    for row in rows[:max_rows]:
        if isinstance(row, dict):
            lines.append("\t".join(str(row.get(c, "")) for c in columns))
        elif isinstance(row, (list, tuple)):
            lines.append("\t".join(str(v) for v in row))
    return "\n".join(lines)


def _preset_sql(question: str) -> Optional[tuple[str, str]]:
    """자주 쓰는 고위험 질문은 검증된 SQL을 우선 사용"""
    q = question.replace(" ", "")
    if "생산량" in q and "라인별" in q:
        sql = (
            "SELECT TOP 100 "
            "COALESCE(NULLIF(L.PROCESSSEGMENTID, ''), NULLIF(L.PROCESSNODEID, ''), '미지정') AS 라인명, "
            "SUM(ISNULL(L.QTY, 0)) AS 생산량, "
            "COUNT(*) AS LOT건수 "
            "FROM CIM_LOT L WITH (NOLOCK) "
            "WHERE L.LASTEVENTTIME >= DATEADD(day, -7, DATEADD(year, -1, GETDATE())) "
            "AND L.LASTEVENTTIME < DATEADD(year, -1, GETDATE()) "
            "GROUP BY COALESCE(NULLIF(L.PROCESSSEGMENTID, ''), NULLIF(L.PROCESSNODEID, ''), '미지정') "
            "ORDER BY 생산량 DESC, LOT건수 DESC"
        )
        return sql, "이번 주 기준 라인별 생산량과 LOT 건수를 집계합니다."
    if "불량률" in q and "공정" in q:
        sql = (
            "SELECT TOP 100 "
            "D.공정, "
            "D.불량수량, "
            "P.생산수량, "
            "CAST(D.불량수량 * 100.0 / NULLIF(P.생산수량, 0) AS decimal(18, 2)) AS 불량률 "
            "FROM ("
            "SELECT COALESCE(NULLIF(PROCESSSEGMENTID, ''), NULLIF(PROCESSNODEID, ''), '미지정') AS 공정, "
            "SUM(ISNULL(DEFECTQTY, 0)) AS 불량수량 "
            "FROM CIM_LOTDEFECT WITH (NOLOCK) "
            "WHERE LASTEVENTTIME >= CAST(DATEADD(year, -1, GETDATE()) AS date) "
            "AND LASTEVENTTIME < DATEADD(day, 1, CAST(DATEADD(year, -1, GETDATE()) AS date)) "
            "GROUP BY COALESCE(NULLIF(PROCESSSEGMENTID, ''), NULLIF(PROCESSNODEID, ''), '미지정')"
            ") D "
            "LEFT JOIN ("
            "SELECT COALESCE(NULLIF(PROCESSSEGMENTID, ''), NULLIF(PROCESSNODEID, ''), '미지정') AS 공정, "
            "SUM(ISNULL(QTY, 0)) AS 생산수량 "
            "FROM CIM_LOT WITH (NOLOCK) "
            "WHERE LASTEVENTTIME >= CAST(DATEADD(year, -1, GETDATE()) AS date) "
            "AND LASTEVENTTIME < DATEADD(day, 1, CAST(DATEADD(year, -1, GETDATE()) AS date)) "
            "GROUP BY COALESCE(NULLIF(PROCESSSEGMENTID, ''), NULLIF(PROCESSNODEID, ''), '미지정')"
            ") P ON D.공정 = P.공정 "
            "ORDER BY 불량률 DESC, D.불량수량 DESC"
        )
        return sql, "오늘 기준 공정별 불량수량, 생산수량, 불량률을 집계합니다."
    if "설비" in q and "가동" in q and "추이" in q:
        sql = (
            "SELECT TOP 100 "
            "CONVERT(date, L.TRACKINTIME) AS 작업일자, "
            "COUNT(*) AS 가동건수, "
            "SUM(ISNULL(L.QTY, 0)) AS 처리수량 "
            "FROM CIM_LOT L WITH (NOLOCK) "
            "WHERE L.TRACKINTIME >= DATEADD(month, DATEDIFF(month, 0, DATEADD(month, -1, DATEADD(year, -1, GETDATE()))), 0) "
            "AND L.TRACKINTIME < DATEADD(month, DATEDIFF(month, 0, DATEADD(year, -1, GETDATE())), 0) "
            "GROUP BY CONVERT(date, L.TRACKINTIME) "
            "ORDER BY 작업일자 ASC"
        )
        return sql, "지난달 기준 일자별 설비 가동 건수와 처리수량 추이를 집계합니다."
    if "작업자별" in q and "생산" in q:
        sql = (
            "SELECT TOP 100 "
            "COALESCE(NULLIF(L.TRACKOUTUSERNAME, ''), NULLIF(L.TRACKOUTUSER, ''), NULLIF(L.TRACKINUSERNAME, ''), NULLIF(L.TRACKINUSER, ''), '미지정') AS 작업자, "
            "COUNT(*) AS 작업건수, "
            "SUM(ISNULL(L.QTY, 0)) AS 생산수량, "
            "SUM(ISNULL(L.LOSSQTY, 0)) AS 불량수량, "
            "CAST(SUM(ISNULL(L.LOSSQTY, 0)) * 100.0 / NULLIF(SUM(ISNULL(L.ORIGINALQTY, 0)), 0) AS decimal(18, 2)) AS 불량률 "
            "FROM CIM_LOT L WITH (NOLOCK) "
            "WHERE L.LASTEVENTTIME >= DATEADD(day, -30, DATEADD(year, -1, GETDATE())) "
            "AND L.LASTEVENTTIME < DATEADD(year, -1, GETDATE()) "
            "GROUP BY COALESCE(NULLIF(L.TRACKOUTUSERNAME, ''), NULLIF(L.TRACKOUTUSER, ''), NULLIF(L.TRACKINUSERNAME, ''), NULLIF(L.TRACKINUSER, ''), '미지정') "
            "ORDER BY 생산수량 DESC, 작업건수 DESC"
        )
        return sql, "최근 30일 기준 작업자별 생산수량, 작업건수, 불량률을 비교합니다."
    if "납기" in q and "준수율" in q:
        sql = (
            "SELECT TOP 100 "
            "COUNT(*) AS 전체작업지시, "
            "SUM(CASE WHEN PO.DELIVERYDATE IS NOT NULL AND PO.ENDTIME IS NOT NULL AND PO.ENDTIME <= PO.DELIVERYDATE THEN 1 ELSE 0 END) AS 납기준수건수, "
            "SUM(CASE WHEN PO.DELIVERYDATE IS NOT NULL AND (PO.ENDTIME IS NULL OR PO.ENDTIME > PO.DELIVERYDATE) THEN 1 ELSE 0 END) AS 납기미준수건수, "
            "CAST(SUM(CASE WHEN PO.DELIVERYDATE IS NOT NULL AND PO.ENDTIME IS NOT NULL AND PO.ENDTIME <= PO.DELIVERYDATE THEN 1 ELSE 0 END) * 100.0 / NULLIF(SUM(CASE WHEN PO.DELIVERYDATE IS NOT NULL THEN 1 ELSE 0 END), 0) AS decimal(18, 2)) AS 납기준수율 "
            "FROM CIM_PRODUCTORDER PO WITH (NOLOCK) "
            "WHERE PO.DELIVERYDATE >= DATEADD(quarter, DATEDIFF(quarter, 0, DATEADD(year, -1, GETDATE())), 0) "
            "AND PO.DELIVERYDATE < DATEADD(quarter, DATEDIFF(quarter, 0, DATEADD(year, -1, GETDATE())) + 1, 0)"
        )
        return sql, "이번 분기 기준 제품 작업지시의 납기 준수율을 계산합니다."
    if "불량" in q and "유형" in q:
        sql = (
            "SELECT TOP 100 "
            "COALESCE(NULLIF(D.DEFECTTYPENAME, ''), NULLIF(D.DEFECTNAME, ''), LD.DEFECTID) AS 불량유형, "
            "SUM(ISNULL(LD.DEFECTQTY, 0)) AS 불량수량, "
            "COUNT(*) AS 발생건수 "
            "FROM CIM_LOTDEFECT LD WITH (NOLOCK) "
            "LEFT JOIN CIM_DEFECT D WITH (NOLOCK) ON LD.DEFECTID = D.DEFECTID AND LD.SITEID = D.SITEID "
            "WHERE LD.LASTEVENTTIME >= DATEADD(day, -7, DATEADD(year, -1, GETDATE())) "
            "AND LD.LASTEVENTTIME < DATEADD(year, -1, GETDATE()) "
            "GROUP BY COALESCE(NULLIF(D.DEFECTTYPENAME, ''), NULLIF(D.DEFECTNAME, ''), LD.DEFECTID) "
            "ORDER BY 불량수량 DESC, 발생건수 DESC"
        )
        return sql, "최근 7일간 불량 유형별 불량수량과 발생건수를 집계합니다."
    return None


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@router.post("/nl-to-sql")
async def nl_to_sql(req: NlToSqlRequest):
    """
    자연어 → RAG 컨텍스트 → Ollama SQL 생성 → mes-api 실행
    반환: { success, sql, description, data }
    """
    preset = _preset_sql(req.question)
    term_resolution = None
    term_context = format_term_resolution_for_prompt(None)
    term_user_note = ""

    if preset:
        sql, description = preset
        generated_by_llm = False
        schema_ctx = ""
        db_context = ""
    else:
        # 1. RAG: 관련 스키마 청크 조회
        try:
            schema_ctx = retrieve_context(req.question)
        except Exception as e:
            schema_ctx = "(스키마 정보 조회 실패)"
            print(f"[RAG] 오류: {e}")

        # 2. 모호어가 있을 때만 역할 기반 의미 해석 경로를 활성화
        ambiguous_terms = detect_ambiguous_terms(req.question)

        # 3. 실제 DB 탐색과 모호어 후보 생성을 병렬 수행
        try:
            if ambiguous_terms:
                db_context, term_prepared = await asyncio.gather(
                    build_live_db_context(schema_ctx),
                    prepare_term_resolution_context(
                        question=req.question,
                        user_role=req.user_role,
                        current_view=req.current_view,
                        conversation_context=req.conversation_context,
                        schema_context=schema_ctx,
                    ),
                )
            else:
                db_context = await build_live_db_context(schema_ctx)
                term_prepared = ("(모호어 없음: 일반 NL2SQL 경로 사용)", None)
        except Exception as e:
            db_context = "(실제 MES DB 탐색 실패)"
            term_prepared = ("(모호어 후보 생성 실패)", None)
            print(f"[CONTEXT] 오류: {e}")
        term_context, term_fallback = term_prepared

        # 4. 단일 LLM 호출: 모호어가 있을 때만 역할 기반 의미 해석 반영
        prompt_schema_ctx = _clip_prompt_text(schema_ctx, 450)
        prompt_db_context = _clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 120)
        prompt_term_context = _clip_prompt_text(term_context, 220)
        prompt = NL_TO_SQL_PROMPT.format(
            schema=prompt_schema_ctx,
            db_context=prompt_db_context,
            term_context=prompt_term_context,
            question=_clip_prompt_text(req.question, 150),
        )
        try:
            sql, description, resolved_terms = await _llm_sql_from_prompt(prompt, max_tokens=320)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"LLM 연결 오류: {e}")

        if ambiguous_terms:
            sql, alignment_notes = align_sql_with_live_candidates(sql, term_fallback)
            term_resolution = finalize_term_resolution(
                resolved_terms,
                term_fallback,
                sql,
                alignment_notes,
            )
            term_context = format_term_resolution_for_prompt(term_resolution)
            term_user_note = format_term_resolution_for_user(term_resolution)
        else:
            term_resolution = None
            term_context = format_term_resolution_for_prompt(None)
            term_user_note = ""
        if not description:
            description = f'"{req.question}" 조회 결과'
        generated_by_llm = True

    # 4. DB 실행 (mes-api 위임). LLM 생성 SQL은 실패 시 오류를 넣어 재시도.
    db_data = None
    db_error = None
    max_attempts = 2 if generated_by_llm else 1
    for attempt in range(max_attempts):
        preflight_errors = validate_sql_against_schema(sql) + _semantic_sql_errors(req.question, sql, term_resolution)
        if preflight_errors:
            db_error = "SQL 사전 검증 실패: " + "; ".join(preflight_errors)
            print(f"[SQL_SCHEMA] 오류(attempt {attempt + 1}/{max_attempts}): {db_error}")
            if not generated_by_llm or attempt >= max_attempts - 1:
                break

            repair_prompt = SQL_REPAIR_PROMPT.format(
                schema=_clip_prompt_text(schema_ctx, 500),
                db_context=_clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 150),
                term_context=_clip_prompt_text(term_context, 250),
                question=_clip_prompt_text(req.question, 200),
                sql=_clip_prompt_text(sql, 600),
                error=_clip_prompt_text(db_error, 300),
            )
            try:
                repaired_sql, repaired_description, _ = await _llm_sql_from_prompt(repair_prompt, max_tokens=320)
                sql = repaired_sql
                if repaired_description:
                    description = repaired_description
                continue
            except Exception as repair_error:
                db_error = f"{db_error} / SQL 수정 실패: {repair_error}"
                break

        try:
            db_result = await execute_sql(sql, limit=req.limit)
            # rows를 dict 배열 형식으로 정규화
            db_data = {
                "columns": db_result.get("columns", []),
                "rows": db_result.get("rows", []),   # [{col: val, ...}]
                "count": db_result.get("count", 0),
            }
            db_error = None
            break
        except Exception as e:
            db_error = str(e)
            print(f"[DB] 오류(attempt {attempt + 1}/{max_attempts}): {e}")
            if not generated_by_llm or attempt >= max_attempts - 1:
                break

            repair_prompt = SQL_REPAIR_PROMPT.format(
                schema=_clip_prompt_text(schema_ctx, 500),
                db_context=_clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 150),
                term_context=_clip_prompt_text(term_context, 250),
                question=_clip_prompt_text(req.question, 200),
                sql=_clip_prompt_text(sql, 600),
                error=_clip_prompt_text(db_error, 300),
            )
            try:
                repaired_sql, repaired_description, _ = await _llm_sql_from_prompt(repair_prompt, max_tokens=320)
                sql = repaired_sql
                if repaired_description:
                    description = repaired_description
            except Exception as repair_error:
                db_error = f"{db_error} / SQL 수정 실패: {repair_error}"
                break

    return {
        "success": True,
        "sql": sql,
        "description": description,
        "data": db_data,
        "db_error": db_error,
        "term_resolution": term_resolution,
        "term_note": term_user_note,
    }


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """
    조회된 데이터 + 사용자 질문 → Ollama 분석 텍스트 반환
    """
    if not req.data:
        return {"success": True, "answer": "분석할 데이터가 없습니다. 먼저 데이터를 조회해 주세요."}

    columns = req.data.get("columns", [])
    rows = req.data.get("rows", [])
    rows_text = _rows_to_text(columns, rows)

    prompt = ANALYZE_PROMPT.format(
        columns=", ".join(str(c) for c in columns),
        rows=rows_text,
        question=req.question,
    )
    try:
        answer = await llm_generate(prompt, temperature=0.3, max_tokens=400)
        return {"success": True, "answer": answer}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM 연결 오류: {e}")


@router.get("/health")
async def chat_health():
    """LLM 연결 상태 확인"""
    llm_ok = await check_ollama()
    return {
        "provider": LLM_PROVIDER,
        "llm": "ok" if llm_ok else "연결 실패",
        "model": LLM_MODEL,
    }
