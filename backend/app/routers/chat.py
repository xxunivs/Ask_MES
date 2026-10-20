"""
/chat 라우터
  POST /chat/nl-to-sql   : 자연어 → SQL 생성 + DB 실행
  POST /chat/analyze     : 조회된 데이터에 대한 분석 질문
  GET  /chat/health      : LLM 연결 상태 확인
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from app.core.llm import llm_generate, check_ollama
from app.core.config import LLM_MODEL, LLM_PROVIDER
from app.core.retriever import retrieve_context
from app.core.sql_executor import execute_sql
from app.core.live_sample import build_live_db_context, validate_sql_against_schema
from app.core.sql_validator import allowed_tables_hint, validate_sql
from app.core.query_safety import validate_query
from app.core.sql_autofix import autofix_sql
from app.core.code_values import code_values_prompt_hint
from app.core.concept_alignment import alignment_prompt_rules
from app.core.date_policy import date_rules_for_prompt

router = APIRouter()

# SQL 사전 검증 실패 시 재생성 횟수 / DB 실행 실패 시 재생성 횟수
SCHEMA_RETRY_MAX = 1
DB_RETRY_MAX = 1

# ─────────────────────────────────────────────
# 요청/응답 모델
# ─────────────────────────────────────────────

class NlToSqlRequest(BaseModel):
    question: str
    limit: int = 100


class AnalyzeRequest(BaseModel):
    question: str
    data: Optional[dict] = None  # { columns: [...], rows: [{...}] }


# ─────────────────────────────────────────────
# 프롬프트 템플릿
# ─────────────────────────────────────────────

def _static_prompt_hints() -> dict:
    """이식한 검증 모듈들이 만드는 프롬프트 절. NL_TO_SQL_PROMPT 의 고정 슬롯을 채운다."""
    return {
        "date_rules": date_rules_for_prompt(),
        "schema_whitelist": allowed_tables_hint(),
        "code_values": code_values_prompt_hint() or "(코드값 사전 없음)",
        "alignment_rules": alignment_prompt_rules(),
    }


NL_TO_SQL_PROMPT = """MES 질문을 간결한 MS SQL Server SELECT로 변환하세요.

## 스키마
{schema}

## 실제 DB
{db_context}

## 규칙
1. SELECT 문만 생성 (INSERT/UPDATE/DELETE/DROP/EXEC 절대 금지)
2. MS SQL Server 문법 사용. WITH (NOLOCK) 힌트를 모든 테이블에 적용하세요.
3. 컬럼/테이블명은 반드시 스키마에 있는 이름 그대로 사용 (존재하지 않는 컬럼 사용 금지)

## 날짜 규칙
{date_rules}

## 집계/추이 규칙
9. 일별 추이 집계 시 날짜 컬럼은 CONVERT(date, 날짜컬럼) 사용
10. 설비 가동 횟수 추이 → CIM_LOT 테이블의 TRACKINTIME + EQUIPMENTID로 COUNT(*) 집계
    (CIM_EQUIPMENT.RUNCOUNT는 현재 누적값이므로 추이 분석에 사용 금지)
11. 불량률 계산 → SUM(LOSSQTY) / NULLIF(SUM(ORIGINALQTY), 0) * 100

## alias 규칙
12. 컬럼 alias에 SQL 예약어 사용 금지: DATE, TIME, NAME, VALUE, COUNT, STATE, TYPE, DATA, KEY, INDEX, ORDER
    예시: AS DATE (X) → AS 작업일자 (O), AS COUNT (X) → AS 건수 (O)

## 스키마 화이트리스트 (필수)
13. 아래에 없는 CIM_* 테이블·컬럼 이름을 만들지 마세요.
{schema_whitelist}

## 코드값 (DB DISTINCT 기준, WHERE 절 리터럴)
14. Y/N 플래그는 TRUE/FALSE/1/0 대신 아래 허용 값만 사용.
{code_values}

## 질의-테이블 매핑
15. 아래 질의 유형은 지정 테이블을 반드시 사용.
{alignment_rules}

## 단순 조회 (중요)
16. 단일 테이블로 답할 수 있는 목록·집계·필터 질의는 **JOIN 하지 마세요**.
17. SELECT * 금지. 스키마에 있는 컬럼만 명시.
18. 환각 컬럼 금지: NODENAME→PROCESSNODENAME, SEGMENTNAME→PROCESSSEGMENTNAME, ORDERID→PRODUCTORDERID, SAFETYSTOCKYN→SAFETY_QTY, 자재이름 LOTNAME→MATERIALLOTNAME
19. **SELECT DISTINCT 금지.** 일부 테이블에서 DB 오류 발생. 대신 SELECT TOP 1000 또는 GROUP BY 사용.
    예시: SELECT DISTINCT FACILITYID (X) → SELECT TOP 1000 FACILITYID (O)
20. **컬럼 alias에 작은따옴표(\' \') 사용 금지.** 예: AS \'이름\' (X) → AS 이름 (O)
21. **테이블 alias는 반드시 WITH (NOLOCK) 앞에 위치.** 예: FROM CIM_LOT WITH(NOLOCK) L (X) → FROM CIM_LOT L WITH(NOLOCK) (O)
22. **테이블을 괄호로 감싸지 마세요.** 예: FROM (CIM_LOT WITH(NOLOCK)) (X) → FROM CIM_LOT WITH(NOLOCK) (O)
23. **목록·조회 질의에는 반드시 행 수를 제한하세요.** WHERE 조건이 없으면 `SELECT TOP 1000` 을 붙입니다.
    제한 없는 전체 조회는 차단됩니다. 예: SELECT LOTID FROM CIM_LOT WITH(NOLOCK) (X)
    → SELECT TOP 1000 LOTID FROM CIM_LOT WITH(NOLOCK) (O)
    (COUNT/SUM 등 집계만 하는 질의는 제한이 필요 없습니다)
24. **컬럼 alias 에 공백을 쓰지 마세요.** 예: AS LOT 건수 (X) → AS LOT건수 (O)

첫 글자부터 한 줄 JSON만 응답하고 사고과정·설명·마크다운은 출력하지 마세요:
{{"sql":"SELECT ..."}}

## 질문
{question}

JSON 응답:"""


SQL_REPAIR_PROMPT = """아래 SQL을 오류 한 가지만 반영해 간결한 MS SQL Server SELECT로 수정하세요.

## MES 스키마 정보
{schema}

## 실제 MES DB 탐색 결과
{db_context}

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
    # 마크다운 코드블록 제거. ```json 뿐 아니라 ```sql, ```tsql 등도 벗긴다.
    raw = re.sub(r"```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()

    # JSON 블록 추출 시도: 모델이 뒤에 예시를 이어 쓰는 경우가 있어 첫 valid object만 사용
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start():])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    # Fallback: SELECT 구문 직접 추출.
    # 못 찾으면 빈 문자열을 준다. 예전에는 raw 를 그대로 돌려줘서, 모델이
    # 코드펜스만 뱉고 끊긴 경우(```sql) 찌꺼기 "sql" 이 SQL 로 실행됐다.
    sql_match = re.search(r'(SELECT\s.+?)(?:;|$)', raw, re.DOTALL | re.IGNORECASE)
    sql = sql_match.group(1).strip() if sql_match else ""
    return {"sql": sql, "description": ""}


def _semantic_sql_errors(question: str, sql: str) -> list[str]:
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
    if any(token in q for token in ("가동", "정지")) and "CIM_EQUIPMENT" not in upper_sql and "CIM_LOT" not in upper_sql:
        errors.append("가동/정지 질문은 CIM_EQUIPMENT 또는 CIM_LOT 테이블을 사용해야 합니다.")
    if "완료" in q and "완료" not in "생산완료설비완료" and "CIM_LOT" not in upper_sql and "CIM_PRODUCTORDER" not in upper_sql:
        errors.append("완료 현황 질문은 CIM_LOT(TRACKOUTTIME) 또는 CIM_PRODUCTORDER(ENDTIME)를 사용해야 합니다.")
    return errors


async def _llm_sql_from_prompt(prompt: str, max_tokens: int = 256) -> tuple[str, str, str]:
    raw_response = await llm_generate(prompt, temperature=0.05, max_tokens=max_tokens)
    parsed = _parse_llm_json(raw_response)
    sql = str(parsed.get("sql", ""))
    description = str(parsed.get("description", ""))
    if not sql:
        print(f"[LLM_SQL_RAW] {raw_response[:800]}")
        raise HTTPException(status_code=500, detail="SQL 생성 실패 — LLM 응답을 파싱할 수 없습니다.")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise HTTPException(status_code=500, detail=f"SQL 생성 실패 — SELECT 문이 아닙니다: {sql[:120]}")
    return sql, description, raw_response


def _split_schema_context(schema_ctx: str) -> list[tuple[str, str]]:
    """retrieve_context 결과를 처리 과정 표시용 단계로 분리"""
    labels = {
        "## 개념 매핑": "1-2. 개념 사전 매핑",
        "## JOIN 경로 힌트": "2. JOIN 경로 계산",
    }
    parts = re.split(r"\n\s*(?=## )", schema_ctx)
    steps = [("1-1. 벡터 검색", parts[0].strip())]
    for part in parts[1:]:
        title = next((v for k, v in labels.items() if part.startswith(k)), part.split("\n", 1)[0])
        steps.append((title, part.split("\n", 1)[1].strip() if "\n" in part else ""))
    return steps


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
            "WHERE L.LASTEVENTTIME >= DATEADD(day, -7, '2026-05-22') "
            "AND L.LASTEVENTTIME < '2026-05-22' "
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
            "WHERE LASTEVENTTIME >= '2026-05-22' "
            "AND LASTEVENTTIME < DATEADD(day, 1, '2026-05-22') "
            "GROUP BY COALESCE(NULLIF(PROCESSSEGMENTID, ''), NULLIF(PROCESSNODEID, ''), '미지정')"
            ") D "
            "LEFT JOIN ("
            "SELECT COALESCE(NULLIF(PROCESSSEGMENTID, ''), NULLIF(PROCESSNODEID, ''), '미지정') AS 공정, "
            "SUM(ISNULL(QTY, 0)) AS 생산수량 "
            "FROM CIM_LOT WITH (NOLOCK) "
            "WHERE LASTEVENTTIME >= '2026-05-22' "
            "AND LASTEVENTTIME < DATEADD(day, 1, '2026-05-22') "
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
            "WHERE L.TRACKINTIME >= DATEADD(month, DATEDIFF(month, 0, DATEADD(month, -1, '2026-05-22')), 0) "
            "AND L.TRACKINTIME < DATEADD(month, DATEDIFF(month, 0, '2026-05-22'), 0) "
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
            "WHERE L.LASTEVENTTIME >= DATEADD(day, -30, '2026-05-22') "
            "AND L.LASTEVENTTIME < '2026-05-22' "
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
            "WHERE PO.DELIVERYDATE >= DATEADD(quarter, DATEDIFF(quarter, 0, '2026-05-22'), 0) "
            "AND PO.DELIVERYDATE < DATEADD(quarter, DATEDIFF(quarter, 0, '2026-05-22') + 1, 0)"
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
            "WHERE LD.LASTEVENTTIME >= DATEADD(day, -7, '2026-05-22') "
            "AND LD.LASTEVENTTIME < '2026-05-22' "
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
    # 처리 과정 표시용 단계별 중간 결과
    trace: list[dict[str, str]] = []

    def log(step: str, detail: str) -> None:
        trace.append({"step": step, "detail": detail})

    if preset:
        sql, description = preset
        generated_by_llm = False
        schema_ctx = ""
        db_context = ""
        log("단골 질문", "추천 질문과 일치해 미리 작성된 SQL을 사용 (LLM 미사용)")
    else:
        # 1. RAG: 관련 스키마 청크 조회
        try:
            schema_ctx = retrieve_context(req.question)
        except Exception as e:
            schema_ctx = "(스키마 정보 조회 실패)"
            print(f"[RAG] 오류: {e}")
        for step, detail in _split_schema_context(schema_ctx):
            log(step, detail)

        # 2. 실제 DB 샘플 탐색
        try:
            db_context = await build_live_db_context(schema_ctx)
        except Exception as e:
            db_context = "(실제 MES DB 탐색 실패)"
            print(f"[CONTEXT] 오류: {e}")
        log("3. 실제 값 확인", db_context or "(관련 테이블의 실제 DB 샘플 없음)")

        # 3. SQL 생성
        prompt = NL_TO_SQL_PROMPT.format(
            schema=schema_ctx,
            db_context=db_context or "(관련 테이블의 실제 DB 샘플 없음)",
            question=req.question,
            **_static_prompt_hints(),
        )
        log("4. LLM에 보낸 프롬프트", prompt)
        try:
            sql, description, raw = await _llm_sql_from_prompt(prompt, max_tokens=320)
            log("4. LLM 응답", raw)
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
    max_attempts = (SCHEMA_RETRY_MAX + DB_RETRY_MAX) if generated_by_llm else 1
    for attempt in range(max_attempts):
        attempt_label = f" (시도 {attempt + 1})"
        sql, _autofixes = autofix_sql(sql)
        if _autofixes:
            print(f"[AUTOFIX] {_autofixes}")
        log("5. 자동 교정" + attempt_label, "\n".join(_autofixes) if _autofixes else "교정 없음")
        safety = validate_query(sql)
        preflight_errors = validate_sql_against_schema(sql) + _semantic_sql_errors(req.question, sql)
        # 벤치마크와 동일한 검증기 (스키마, 코드값, 질의-테이블 정합성)
        schema_vr = validate_sql(sql, question=req.question)
        if not schema_vr.ok:
            preflight_errors = [schema_vr.error_message()] + preflight_errors
        if not safety.ok:
            # Query Safety Layer: 파스트리로 DDL/DML·전체 스캔·시스템 테이블을 막는다.
            preflight_errors = [f"[SafetyLayer] {safety.error_message()}"] + preflight_errors
        log("6. 검증" + attempt_label, "\n".join(preflight_errors) if preflight_errors else f"통과\n{sql}")
        if preflight_errors:
            db_error = "SQL 사전 검증 실패: " + "; ".join(preflight_errors)
            print(f"[SQL_SCHEMA] 오류(attempt {attempt + 1}/{max_attempts}): {db_error}")
            if not generated_by_llm or attempt >= max_attempts - 1:
                break

            repair_prompt = SQL_REPAIR_PROMPT.format(
                schema=schema_ctx,
                db_context=db_context or "(관련 테이블의 실제 DB 샘플 없음)",
                question=req.question,
                sql=sql,
                error=db_error,
            )
            try:
                repaired_sql, repaired_description, raw = await _llm_sql_from_prompt(repair_prompt, max_tokens=320)
                log("다시 쓰기" + attempt_label, raw)
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
            log("7. 실행" + attempt_label, f"{db_data['count']}행 반환")
            break
        except Exception as e:
            db_error = str(e)
            print(f"[DB] 오류(attempt {attempt + 1}/{max_attempts}): {e}")
            log("7. 실행" + attempt_label, f"DB 오류: {db_error}")
            if not generated_by_llm or attempt >= max_attempts - 1:
                break

            repair_prompt = SQL_REPAIR_PROMPT.format(
                schema=schema_ctx,
                db_context=db_context or "(관련 테이블의 실제 DB 샘플 없음)",
                question=req.question,
                sql=sql,
                error=db_error,
            )
            try:
                repaired_sql, repaired_description, raw = await _llm_sql_from_prompt(repair_prompt, max_tokens=320)
                log("다시 쓰기" + attempt_label, raw)
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
        "trace": trace,
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
