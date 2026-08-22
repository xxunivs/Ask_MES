"""
/chat 라우터
  POST /chat/nl-to-sql   : 자연어 → SQL 생성 + DB 실행
  POST /chat/analyze     : 조회된 데이터에 대한 분석 질문
  GET  /chat/health      : LLM 연결 상태 확인
"""
from __future__ import annotations

import asyncio
import json
import os
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
    ROLE_TERM_KPI_POLICIES,
    align_sql_with_live_candidates,
    detect_ambiguous_terms,
    finalize_term_resolution,
    format_term_resolution_for_prompt,
    format_term_resolution_for_user,
    prepare_term_resolution_context,
    resolve_ambiguous_terms,
)

router = APIRouter()
_BASE_DIR = os.path.dirname(__file__)
_SCHEMA_PATH = os.path.join(_BASE_DIR, "../data/mes_schema.json")
_SCHEMA_CACHE: dict[str, dict[str, Any]] | None = None

# 데모용 날짜 앵커 — DB 최신 데이터 기준일로 고정 (실제 운영 시 "'GETDATE()'" 으로 변경)
_DATE_ANCHOR = "'2026-05-22'"

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


def _load_schema() -> dict[str, dict[str, Any]]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    tables: dict[str, dict[str, Any]] = {}
    for table in raw.get("tables", []):
        name = str(table.get("name", "")).upper()
        if not name:
            continue
        tables[name] = {
            "description": table.get("description", ""),
            "columns": table.get("columns", []),
        }
    _SCHEMA_CACHE = tables
    return tables


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


def _columns_for_table(table: str) -> list[str]:
    schema = _load_schema()
    return [str(col.get("name", "")).upper() for col in schema.get(table.upper(), {}).get("columns", [])]


def _qualified_ref(table: str, alias: str, column: str) -> str:
    return f"{alias}.[{column}]"


def _split_column_ref(column_ref: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*(CIM_[A-Z0-9_]+)\.([A-Z0-9_]+)\s*$", column_ref.upper())
    if not match:
        return None
    return match.group(1), match.group(2)


def _preferred_time_column(table: str) -> str | None:
    columns = _columns_for_table(table)
    for name in ("LASTEVENTTIME", "TRACKINTIME", "CREATEDTIME", "ENDTIME", "DELIVERYDATE", "DUEDATE"):
        if name in columns:
            return name
    return None


def _dimension_expression(question: str, table: str, alias: str) -> tuple[str, str, str] | None:
    columns = _columns_for_table(table)
    compact = question.replace(" ", "")

    if "라인별" in compact or "공정별" in compact:
        if "PROCESSSEGMENTID" in columns or "PROCESSNODEID" in columns:
            left = _qualified_ref(table, alias, "PROCESSSEGMENTID") if "PROCESSSEGMENTID" in columns else "''"
            right = _qualified_ref(table, alias, "PROCESSNODEID") if "PROCESSNODEID" in columns else "''"
            expr = f"COALESCE(NULLIF({left}, ''), NULLIF({right}, ''), '미지정')"
            return expr, expr, "공정"

    if "설비별" in compact and "EQUIPMENTID" in columns:
        expr = _qualified_ref(table, alias, "EQUIPMENTID")
        return expr, expr, "설비"

    if "제품별" in compact:
        for name in ("PRODUCTDEFINITIONID", "PRODUCTID"):
            if name in columns:
                expr = _qualified_ref(table, alias, name)
                return expr, expr, "제품"

    if "작업자별" in compact:
        user_cols = [name for name in ("TRACKOUTUSERNAME", "TRACKOUTUSER", "TRACKINUSERNAME", "TRACKINUSER") if name in columns]
        if user_cols:
            expr = "COALESCE(" + ", ".join(f"NULLIF({_qualified_ref(table, alias, name)}, '')" for name in user_cols) + ", '미지정')"
            return expr, expr, "작업자"

    return None


def _time_window_clause(question: str, table: str, alias: str, time_column: str | None) -> str:
    if not time_column:
        return ""

    col = _qualified_ref(table, alias, time_column)
    anchor = _DATE_ANCHOR
    compact = question.replace(" ", "")

    if "최근7일" in compact or "7일간" in compact:
        return f"{col} >= DATEADD(day, -7, {anchor}) AND {col} < {anchor}"
    if "최근30일" in compact or "30일간" in compact:
        return f"{col} >= DATEADD(day, -30, {anchor}) AND {col} < {anchor}"
    if "오늘" in compact:
        start = f"CAST({anchor} AS date)"
        return f"{col} >= {start} AND {col} < DATEADD(day, 1, {start})"
    if "이번주" in compact:
        start = f"DATEADD(week, DATEDIFF(week, 0, {anchor}), 0)"
        end = f"DATEADD(week, DATEDIFF(week, 0, {anchor}) + 1, 0)"
        return f"{col} >= {start} AND {col} < {end}"
    if "이번달" in compact:
        start = f"DATEADD(month, DATEDIFF(month, 0, {anchor}), 0)"
        end = f"DATEADD(month, DATEDIFF(month, 0, {anchor}) + 1, 0)"
        return f"{col} >= {start} AND {col} < {end}"
    if "지난달" in compact:
        start = f"DATEADD(month, DATEDIFF(month, 0, DATEADD(month, -1, {anchor})), 0)"
        end = f"DATEADD(month, DATEDIFF(month, 0, {anchor}), 0)"
        return f"{col} >= {start} AND {col} < {end}"
    return f"{col} >= DATEADD(day, -7, {anchor}) AND {col} < {anchor}"


def _wants_date_trend(question: str) -> bool:
    compact = question.replace(" ", "")
    if "일별" in compact or "추이" in compact:
        return True
    if "현황" in compact and not any(token in compact for token in ("설비별", "제품별", "공정별", "라인별", "작업자별")):
        return True
    return False


def _measure_expression(term: str, question: str, table: str, alias: str, column: str, kind: str) -> str | None:
    col = _qualified_ref(table, alias, column)
    compact = question.replace(" ", "")
    upper_column = column.upper()

    if term in {"불량", "손실", "실적"}:
        # kind는 selected_meaning 전체 문자열 ("CIM_LOT.LOSSQTY 기준 수량") — "수량" 포함 여부로 체크
        is_qty_kind = "수량" in kind
        is_qty_col = any(token in upper_column for token in ("QTY", "COUNT", "CNT", "LOSS", "DEFECT", "RESULT"))
        if is_qty_kind or is_qty_col:
            return f"SUM(ISNULL({col}, 0))"
        return None

    if "생산량" in compact and column.upper() == "QTY":
        return f"SUM(ISNULL({col}, 0))"

    return None


def _enforce_kpi_columns_in_sql(
    sql: str,
    term_resolution: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """
    LLM 생성 SQL에 역할 KPI 컬럼이 없으면 강제 교체.
    같은 테이블에서 다른 QTY 계열 컬럼을 사용한 경우에만 교체 (테이블 구조 변경 없이).
    """
    if not term_resolution:
        return sql, []

    QTY_TOKENS = ("QTY", "LOSS", "DEFECT", "RESULT", "COUNT", "CNT")
    patches: list[str] = []

    for item in term_resolution.get("resolved_terms", []) or []:
        term = str(item.get("term", ""))
        if term not in {"불량", "손실", "실적"}:
            continue  # 수량 KPI만 교체 대상

        resolved_cols = item.get("validated_columns") or item.get("selected_columns") or []
        if not resolved_cols:
            continue

        wanted_ref = str(resolved_cols[0])
        match = re.match(r"^\s*(CIM_[A-Z0-9_]+)\.([A-Z0-9_]+)\s*$", wanted_ref.upper())
        if not match:
            continue
        wanted_table, wanted_col = match.groups()

        # 이미 SQL에 있으면 패스
        if wanted_col in sql.upper() and wanted_table in sql.upper():
            continue

        # 같은 테이블에서 QTY 계열 컬럼을 찾아 교체
        if wanted_table not in sql.upper():
            continue  # 테이블 자체가 없으면 교체 불가 (구조 변경 필요 → 스킵)

        candidates = (term_resolution.get("dynamic_candidates") or {}).get(term) or []
        for cand in candidates:
            cand_table = str(cand.get("table", "")).upper()
            cand_col = str(cand.get("column", "")).upper()
            if (
                cand_table == wanted_table
                and cand_col != wanted_col
                and any(tok in cand_col for tok in QTY_TOKENS)
                and re.search(rf"\b{re.escape(cand_col)}\b", sql.upper())
            ):
                sql = re.sub(
                    rf"\b{re.escape(cand_col)}\b",
                    wanted_col,
                    sql,
                    flags=re.IGNORECASE,
                )
                patches.append(f"[역할 KPI 강제 적용] {term}: {cand_col} → {wanted_col}")
                break

    return sql, patches


def _deterministic_sql_description(question: str, term_resolution: dict[str, Any]) -> str:
    term = ((term_resolution.get("resolved_terms") or [{}])[0]).get("term", "모호어")
    return f'"{question}" 질문에서 {term} 해석을 고정한 검증 SQL입니다.'


def _build_completion_sql(question: str, table: str, column: str) -> str | None:
    """완료 KPI: 시간 컬럼이면 일별 완료 추이, STATE면 상태별 건수."""
    alias = "L"
    upper_col = column.upper()
    anchor = _DATE_ANCHOR

    if upper_col in {"TRACKOUTTIME", "ENDTIME", "LOTFINISHEDTIME"}:
        time_col = _qualified_ref(table, alias, column)
        time_filter = _time_window_clause(question, table, alias, column)
        if not time_filter:
            time_filter = f"{time_col} >= DATEADD(day, -7, {anchor}) AND {time_col} < {anchor}"
        date_expr = f"CONVERT(date, {time_col})"
        dimension = _dimension_expression(question, table, alias)

        if dimension:
            qty_part = f", SUM(ISNULL({alias}.[QTY], 0)) AS [완료수량]" if table == "CIM_LOT" else ""
            sql = (
                f"SELECT TOP 20 {dimension[0]} AS [{dimension[2]}], "
                f"COUNT(*) AS [완료건수]{qty_part} "
                f"FROM {table} {alias} WITH (NOLOCK) "
                f"WHERE {time_filter} "
                f"GROUP BY {dimension[1]} "
                f"ORDER BY [완료건수] DESC"
            )
        else:
            qty_part = f", SUM(ISNULL({alias}.[QTY], 0)) AS [완료수량]" if table == "CIM_LOT" else ""
            sql = (
                f"SELECT TOP 20 {date_expr} AS [완료일자], "
                f"COUNT(*) AS [완료건수]{qty_part} "
                f"FROM {table} {alias} WITH (NOLOCK) "
                f"WHERE {time_filter} "
                f"GROUP BY {date_expr} "
                f"ORDER BY [완료일자] ASC"
            )
        return sql

    if upper_col == "STATE":
        time_column = _preferred_time_column(table)
        time_filter = _time_window_clause(question, table, alias, time_column)
        qty_part = f", SUM(ISNULL({alias}.[QTY], 0)) AS [수량]" if table == "CIM_LOT" else ""
        where_clause = f" WHERE {time_filter}" if time_filter else ""
        sql = (
            f"SELECT TOP 20 {alias}.[STATE] AS [상태], COUNT(*) AS [건수]{qty_part} "
            f"FROM {table} {alias} WITH (NOLOCK){where_clause} "
            f"GROUP BY {alias}.[STATE] "
            f"ORDER BY [건수] DESC"
        )
        return sql

    return None


def _build_operation_sql(question: str, table: str, column: str) -> str | None:
    """가동 KPI: CIM_EQUIPMENT이면 설비 상태/건수, CIM_LOT이면 일별 투입 추이."""
    upper_col = column.upper()
    anchor = _DATE_ANCHOR

    if table == "CIM_EQUIPMENT":
        # 예상 외 컬럼이어도 CIM_EQUIPMENT 가동 현황 SQL로 처리
        # RUNCOUNT는 샘플 DB에 값이 없으므로 STATE/STATETIME 기반으로만 조회
        sql = (
            "SELECT TOP 20 E.[EQUIPMENTID], E.[STATE] AS [가동상태], "
            "E.[STATETIME] AS [상태변경시각] "
            "FROM CIM_EQUIPMENT E WITH (NOLOCK) "
            "WHERE E.[STATE] IS NOT NULL "
            "ORDER BY E.[STATETIME] DESC"
        )
        return sql

    if table == "CIM_LOT":
        # TRACKINTIME/TRACKOUTTIME 또는 예상 외 컬럼이어도 LOT 기반 투입 추이로 처리
        time_col_name = column if upper_col in {"TRACKINTIME", "TRACKOUTTIME"} else "TRACKINTIME"
        alias = "L"
        time_col = _qualified_ref(table, alias, time_col_name)
        time_filter = _time_window_clause(question, table, alias, time_col_name)
        if not time_filter:
            time_filter = (
                f"{time_col} >= DATEADD(month, -1, {anchor}) "
                f"AND {time_col} < {anchor}"
            )
        date_expr = f"CONVERT(date, {time_col})"
        sql = (
            f"SELECT TOP 20 {date_expr} AS [작업일자], "
            f"COUNT(*) AS [가동건수], SUM(ISNULL({alias}.[QTY], 0)) AS [처리수량] "
            f"FROM {table} {alias} WITH (NOLOCK) "
            f"WHERE {time_filter} "
            f"GROUP BY {date_expr} "
            f"ORDER BY [작업일자] ASC"
        )
        return sql

    return None


def _build_downtime_sql(question: str, table: str, column: str) -> str | None:
    """정지 KPI: CIM_EQUIPMENT 기반 정지 현황."""
    if table == "CIM_EQUIPMENT":
        # 예상 외 컬럼이어도 CIM_EQUIPMENT 정지 현황 SQL로 처리
        sql = (
            "SELECT TOP 20 E.[EQUIPMENTID], E.[STATE] AS [현재상태], "
            "E.[PREVSTATE] AS [이전상태], E.[STATETIME] AS [상태변경시각] "
            "FROM CIM_EQUIPMENT E WITH (NOLOCK) "
            "WHERE E.[STATE] IS NOT NULL "
            "ORDER BY E.[STATETIME] DESC"
        )
        return sql

    return None


def _kpi_policy_column_ref(user_role: str, term: str) -> tuple[str, str, str] | None:
    """ROLE_TERM_KPI_POLICIES 첫 번째 항목에서 (table, column, kind) 직접 반환.
    LLM term resolution 결과를 무시하고 정책 우선순위를 강제 적용."""
    role = (user_role or "general").lower()
    term_policies = ROLE_TERM_KPI_POLICIES.get(role, {}).get(term)
    if not term_policies:
        # 역할이 없으면 production fallback
        term_policies = ROLE_TERM_KPI_POLICIES.get("production", {}).get(term)
    if not term_policies:
        return None
    first = term_policies[0]
    tables = first.get("tables", ())
    columns = first.get("columns", ())
    if not tables or not columns:
        return None
    return str(tables[0]), str(columns[0]), str(first.get("kind", "값"))


def _patch_term_resolution_with_policy(
    term_resolution: dict[str, Any] | None,
    user_role: str,
) -> None:
    """_build_deterministic_sql이 정책 컬럼을 사용한 후,
    term_resolution의 해석 결과도 실제 사용된 컬럼으로 덮어씀.
    kpi_label까지 덮어써야 format_term_resolution_for_user가 올바른 해석을 표시함."""
    if not term_resolution:
        return
    role = (user_role or "general").lower()
    for item in (term_resolution.get("resolved_terms") or []):
        term = str(item.get("term", ""))
        term_policies = ROLE_TERM_KPI_POLICIES.get(role, {}).get(term)
        if not term_policies:
            term_policies = ROLE_TERM_KPI_POLICIES.get("production", {}).get(term)
        if not term_policies:
            continue
        first = term_policies[0]
        tables = first.get("tables", ())
        columns = first.get("columns", ())
        if not tables or not columns:
            continue
        table, column = str(tables[0]), str(columns[0])
        column_ref = f"{table}.{column}"
        kind = str(first.get("kind", "값"))
        label = str(first.get("label", ""))
        item["selected_columns"] = [column_ref]
        item["validated_columns"] = [column_ref]
        item["selected_meaning"] = f"{column_ref} 기준 {kind}"
        item["kpi_label"] = label  # format_term_resolution_for_user가 이 필드를 최우선 사용


def _build_deterministic_sql(
    question: str,
    term_resolution: dict[str, Any] | None,
) -> str | None:
    if not term_resolution:
        return None

    resolved_terms = term_resolution.get("resolved_terms") or []
    if not resolved_terms:
        return None

    item = resolved_terms[0]
    term = str(item.get("term", ""))
    if term not in {"불량", "손실", "실적", "완료", "가동", "정지"}:
        return None

    # 정책에서 직접 (table, column, kind) 결정 — LLM 결과 무시
    user_role = str(term_resolution.get("user_role", "general"))
    policy_col = _kpi_policy_column_ref(user_role, term)
    if not policy_col:
        return None
    table, column, kind = policy_col

    # 완료/가동/정지: KPI 전용 빌더로 위임
    if term == "완료":
        return _build_completion_sql(question, table, column)
    if term == "가동":
        return _build_operation_sql(question, table, column)
    if term == "정지":
        return _build_downtime_sql(question, table, column)

    # 수량 KPI (불량/손실/실적)
    alias = "L"
    # kind는 정책에서 직접 가져옴 (예: "수량")
    measure_expr = _measure_expression(term, question, table, alias, column, kind)
    if not measure_expr:
        return None

    time_column = _preferred_time_column(table)
    time_filter = _time_window_clause(question, table, alias, time_column)
    dimension = _dimension_expression(question, table, alias)
    wants_date = bool(time_column) and _wants_date_trend(question)

    select_parts: list[str] = []
    group_parts: list[str] = []
    order_clause = "값 DESC"

    if dimension:
        select_parts.append(f"{dimension[0]} AS [{dimension[2]}]")
        group_parts.append(dimension[1])
        order_clause = "값 DESC"
    elif wants_date and time_column:
        date_expr = f"CONVERT(date, {_qualified_ref(table, alias, time_column)})"
        select_parts.append(f"{date_expr} AS [작업일자]")
        group_parts.append(date_expr)
        order_clause = "[작업일자] ASC"

    select_parts.append(f"{measure_expr} AS [값]")

    sql = f"SELECT TOP 20 {', '.join(select_parts)} FROM {table} {alias} WITH (NOLOCK)"
    if time_filter:
        sql += f" WHERE {time_filter}"
    if group_parts:
        sql += f" GROUP BY {', '.join(group_parts)}"
    sql += f" ORDER BY {order_clause}"
    return sql


def _advance_term_resolution_candidate(term_resolution: dict[str, Any] | None) -> dict[str, Any] | None:
    if not term_resolution:
        return None

    resolved_terms = term_resolution.get("resolved_terms") or []
    if not resolved_terms:
        return None

    item = resolved_terms[0]
    term = str(item.get("term", ""))
    current_cols = {str(col).upper() for col in (item.get("selected_columns") or []) if isinstance(col, str)}
    candidates = (term_resolution.get("dynamic_candidates") or {}).get(term) or []
    replacement = next(
        (
            candidate for candidate in candidates
            if candidate.get("db_has_value") is True
            and str(candidate.get("column_ref", "")).upper() not in current_cols
        ),
        None,
    )
    if not replacement:
        return None

    cloned = json.loads(json.dumps(term_resolution))
    target = cloned["resolved_terms"][0]
    column_ref = str(replacement.get("column_ref", ""))
    target["selected_meaning"] = f"{column_ref} 기준 {replacement.get('kind', '값')}"
    target["selected_columns"] = [column_ref]
    target["validated_columns"] = [column_ref]
    evidence = target.get("evidence") or []
    evidence.insert(0, f"빈 결과 재시도: {column_ref} 후보로 교체")
    target["evidence"] = evidence[:8]
    return cloned


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
    if any(token in q for token in ("가동", "정지")) and "CIM_EQUIPMENT" not in upper_sql and "CIM_LOT" not in upper_sql:
        errors.append("가동/정지 질문은 CIM_EQUIPMENT 또는 CIM_LOT 테이블을 사용해야 합니다.")
    if "완료" in q and "완료" not in "생산완료설비완료" and "CIM_LOT" not in upper_sql and "CIM_PRODUCTORDER" not in upper_sql:
        errors.append("완료 현황 질문은 CIM_LOT(TRACKOUTTIME) 또는 CIM_PRODUCTORDER(ENDTIME)를 사용해야 합니다.")

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
    term_resolution = None
    term_context = format_term_resolution_for_prompt(None)
    term_user_note = ""
    term_fallback = None
    deterministic_sql = None

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

        if ambiguous_terms:
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
                print(f"[TERM_RESOLUTION] 오류: {e}")
                term_resolution = term_fallback

            deterministic_sql = _build_deterministic_sql(req.question, term_resolution)
            if deterministic_sql:
                sql = deterministic_sql
                # term_resolution을 실제 사용된 정책 컬럼으로 업데이트
                # (LLM이 고른 컬럼과 다를 수 있으므로 해석 노트도 일치시킴)
                _patch_term_resolution_with_policy(term_resolution, req.user_role)
                description = _deterministic_sql_description(req.question, term_resolution)
                resolved_terms = []
            else:
                prompt_schema_ctx = _clip_prompt_text(schema_ctx, 450)
                prompt_db_context = _clip_prompt_text(db_context or "(관련 테이블의 실제 DB 샘플 없음)", 120)
                prompt_term_context = _clip_prompt_text(
                    format_term_resolution_for_prompt(term_resolution or term_fallback),
                    220,
                )
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

                sql, alignment_notes = align_sql_with_live_candidates(sql, term_fallback)
                # LLM이 역할 KPI 컬럼을 무시했을 경우 강제 교체
                sql, kpi_patches = _enforce_kpi_columns_in_sql(sql, term_resolution or term_fallback)
                if kpi_patches:
                    print(f"[KPI_ENFORCE] {kpi_patches}")
                term_resolution = finalize_term_resolution(
                    resolved_terms,
                    term_fallback,
                    sql,
                    alignment_notes,
                )

            term_context = format_term_resolution_for_prompt(term_resolution)
            term_user_note = format_term_resolution_for_user(term_resolution)
        else:
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
            if (
                deterministic_sql
                and term_resolution
                and db_data.get("count", 0) == 0
                and attempt < max_attempts - 1
            ):
                next_resolution = _advance_term_resolution_candidate(term_resolution)
                if next_resolution:
                    term_resolution = next_resolution
                    term_context = format_term_resolution_for_prompt(term_resolution)
                    term_user_note = format_term_resolution_for_user(term_resolution)
                    rebuilt_sql = _build_deterministic_sql(req.question, term_resolution)
                    if rebuilt_sql and rebuilt_sql != sql:
                        sql = rebuilt_sql
                        description = _deterministic_sql_description(req.question, term_resolution)
                        continue
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
