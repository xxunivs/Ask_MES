"""
/chat 라우터
  POST /chat/nl-to-sql   : 자연어 → SQL 생성 + DB 실행
  POST /chat/analyze     : 조회된 데이터에 대한 분석 질문
  GET  /chat/health      : LLM 연결 상태 확인
"""
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
    format_term_resolution_for_prompt,
    format_term_resolution_for_user,
    resolve_ambiguous_terms,
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

NL_TO_SQL_PROMPT = """당신은 MES(제조실행시스템) 전문 SQL 생성 어시스턴트입니다.
아래 MES 스키마 정보를 참고하여 사용자의 자연어 질문을 MS SQL Server SELECT 쿼리로 변환하세요.

## MES 스키마 정보
{schema}

## 실제 MES DB 탐색 결과
{db_context}

## 모호 제조 용어 해석
{term_context}

## 규칙
1. SELECT 문만 생성 (INSERT/UPDATE/DELETE/DROP/EXEC 절대 금지)
2. MS SQL Server 문법 사용. WITH (NOLOCK) 힌트를 모든 테이블에 적용하세요.
3. 컬럼/테이블명은 반드시 스키마에 있는 이름 그대로 사용 (존재하지 않는 컬럼 사용 금지)
4. 실제 MES DB 탐색 결과에 샘플값/날짜범위/주요값이 있으면 그 값을 우선 참고하세요.
5. 모호 제조 용어 해석 결과가 있으면 해당 의미와 SQL 힌트를 우선 적용하세요.

## 날짜 규칙
6. [중요] 기본 기준일은 항상 1년 전이다. 사용자가 날짜를 별도로 지정하지 않으면 DATEADD(year, -1, GETDATE())를 기준으로 사용하라.
   - "오늘" / 날짜 미지정 → DATEADD(year, -1, GETDATE())
   - "어제" → DATEADD(day, -1, DATEADD(year, -1, CAST(GETDATE() AS date)))
   - "이번 달" → 1년 전 같은 달: YEAR(DATEADD(year,-1,GETDATE())), MONTH(DATEADD(year,-1,GETDATE()))
   - "이번 주" → DATEADD(year,-1,GETDATE()) 기준 해당 주
   - "최근 N일" → DATEADD(day, -N, DATEADD(year, -1, GETDATE())) ~ DATEADD(year, -1, GETDATE())
7. 특정 연도/월이 명시된 경우 (예: "2025년 12월") → 리터럴 날짜 사용 (GETDATE() 계산 금지)
   예시: TRACKINTIME >= '2025-12-01' AND TRACKINTIME < '2026-01-01'
8. 날짜 범위 필터는 BETWEEN보다 >= AND < 형식 사용

## 집계/추이 규칙
9. 일별 추이 집계 시 날짜 컬럼은 CONVERT(date, 날짜컬럼) 사용
10. 설비 가동 횟수 추이 → CIM_LOT 테이블의 TRACKINTIME + EQUIPMENTID로 COUNT(*) 집계
    (CIM_EQUIPMENT.RUNCOUNT는 현재 누적값이므로 추이 분석에 사용 금지)
11. 불량률 계산 → SUM(LOSSQTY) / NULLIF(SUM(ORIGINALQTY), 0) * 100
12. 생산량/생산 실적 질문은 CIM_LOT를 기준 사실 테이블로 사용하세요.
    - 생산량: SUM(CIM_LOT.QTY)
    - 생산건수: COUNT(*)
    - 설비별 생산량: CIM_LOT.EQUIPMENTID 기준 집계 후 CIM_EQUIPMENT와 JOIN해 설비명을 표시
    - 제품별 생산량: CIM_LOT.PRODUCTDEFINITIONID 기준 집계 후 CIM_PRODUCTDEFINITION과 JOIN해 제품명을 표시

## alias 규칙
13. 컬럼 alias에 SQL 예약어 사용 금지: DATE, TIME, NAME, VALUE, COUNT, STATE, TYPE, DATA, KEY, INDEX, ORDER
    예시: AS DATE (X) → AS 작업일자 (O), AS COUNT (X) → AS 건수 (O)

## 응답 형식
반드시 아래 JSON 형식으로만 응답 (마크다운 코드블록 없이):
{{"sql": "SELECT ...", "description": "한국어로 쿼리 설명"}}

## 사용자 질문
{question}

JSON 응답:"""


SQL_REPAIR_PROMPT = """당신은 MES(제조실행시스템) 전문 SQL 수정 어시스턴트입니다.
아래 SQL은 실제 MES DB에서 실행 실패했습니다. 오류와 실제 DB 탐색 결과를 참고해 실행 가능한 MS SQL Server SELECT 쿼리로 고치세요.

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

## 규칙
1. SELECT 문만 생성하세요.
2. WITH (NOLOCK)을 모든 테이블에 적용하세요.
3. 스키마/실제 DB 탐색 결과에 없는 테이블명과 컬럼명을 만들지 마세요.
4. 오류 원인을 반영해 JOIN, 컬럼명, 날짜 조건, 집계식을 수정하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"sql": "SELECT ...", "description": "한국어로 수정 내용 설명"}}

JSON 응답:"""


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

def _parse_llm_json(raw: str) -> tuple[str, str]:
    """LLM 응답에서 sql, description 추출. 실패 시 raw 그대로 반환"""
    # 마크다운 코드블록 제거
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # JSON 블록 추출 시도: 모델이 뒤에 예시를 이어 쓰는 경우가 있어 첫 valid object만 사용
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start():])
            return obj.get("sql", ""), obj.get("description", "")
        except json.JSONDecodeError:
            continue

    # Fallback: SELECT 구문 직접 추출
    sql_match = re.search(r'(SELECT\s.+?)(?:;|$)', raw, re.DOTALL | re.IGNORECASE)
    sql = sql_match.group(1).strip() if sql_match else raw
    return sql, ""


def _clip_prompt_text(text: str, max_chars: int) -> str:
    """Keep prompts below the 4096-token vLLM context limit."""
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
    if not term_resolution:
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


async def _llm_sql_from_prompt(prompt: str) -> tuple[str, str]:
    raw_response = await llm_generate(prompt, temperature=0.05, max_tokens=256)
    sql, description = _parse_llm_json(raw_response)
    if not sql:
        raise HTTPException(status_code=500, detail="SQL 생성 실패 — LLM 응답을 파싱할 수 없습니다.")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise HTTPException(status_code=500, detail=f"SQL 생성 실패 — SELECT 문이 아닙니다: {sql[:120]}")
    return sql, description


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

        # 2. 실제 DB 탐색: 관련 테이블의 샘플/날짜범위/주요값 확인
        try:
            db_context = await build_live_db_context(schema_ctx)
        except Exception as e:
            db_context = "(실제 MES DB 탐색 실패)"
            print(f"[DB_CONTEXT] 오류: {e}")

        # 3. 모호 제조 용어 해석: 역할/맥락 + RAG 스키마 + 실제 DB 탐색 결과 기반 동적 판단
        try:
            term_resolution = await resolve_ambiguous_terms(
                question=req.question,
                user_role=req.user_role,
                current_view=req.current_view,
                conversation_context=req.conversation_context,
                schema_context=schema_ctx,
                db_context=db_context,
            )
        except Exception as e:
            term_resolution = None
            print(f"[TERM_RESOLVER] 오류: {e}")
        term_context = format_term_resolution_for_prompt(term_resolution)
        term_user_note = format_term_resolution_for_user(term_resolution)

        # 4. LLM: SQL 생성
        prompt_schema_ctx = _clip_prompt_text(schema_ctx, 3200)
        prompt_db_context = _clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 900)
        prompt_term_context = _clip_prompt_text(term_context, 1400)
        prompt = NL_TO_SQL_PROMPT.format(
            schema=prompt_schema_ctx,
            db_context=prompt_db_context,
            term_context=prompt_term_context,
            question=req.question,
        )
        try:
            sql, description = await _llm_sql_from_prompt(prompt)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"LLM 연결 오류: {e}")

        if not description:
            description = f'"{req.question}" 조회 결과'
        generated_by_llm = True

    # 4. DB 실행 (mes-api 위임). LLM 생성 SQL은 실패 시 오류를 넣어 재시도.
    db_data = None
    db_error = None
    max_attempts = 3 if generated_by_llm else 1
    for attempt in range(max_attempts):
        preflight_errors = validate_sql_against_schema(sql) + _semantic_sql_errors(req.question, sql, term_resolution)
        if preflight_errors:
            db_error = "SQL 사전 검증 실패: " + "; ".join(preflight_errors)
            print(f"[SQL_SCHEMA] 오류(attempt {attempt + 1}/{max_attempts}): {db_error}")
            if not generated_by_llm or attempt >= max_attempts - 1:
                break

            repair_prompt = SQL_REPAIR_PROMPT.format(
                schema=_clip_prompt_text(schema_ctx, 4200),
                db_context=_clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 1400),
                term_context=_clip_prompt_text(term_context, 1000),
                question=req.question,
                sql=sql,
                error=db_error,
            )
            try:
                repaired_sql, repaired_description = await _llm_sql_from_prompt(repair_prompt)
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
                schema=_clip_prompt_text(schema_ctx, 4200),
                db_context=_clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 1400),
                term_context=_clip_prompt_text(term_context, 1000),
                question=req.question,
                sql=sql,
                error=db_error,
            )
            try:
                repaired_sql, repaired_description = await _llm_sql_from_prompt(repair_prompt)
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
