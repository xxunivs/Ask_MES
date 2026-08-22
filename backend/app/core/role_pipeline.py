"""
역할 기반 모호어 해석 파이프라인.

MES 용어는 역할에 따라 다른 컬럼을 뜻한다. 예를 들어 "불량"은 품질팀에게는
검사 기록(CIM_LOTDEFECT.DEFECTQTY)이고 생산팀에게는 생산 손실(CIM_LOT.LOSSQTY)이다.
이 모듈은 그 해석을 SQL 로 굳히는 쪽을 담당한다.

  - build_deterministic_sql        역할별 KPI 정책으로 SQL 을 규칙 생성
  - enforce_kpi_columns_in_sql     LLM 이 정책 컬럼을 무시했을 때 교체
  - patch_term_resolution_with_policy  실제 사용된 컬럼으로 해석 노트 정정
  - advance_term_resolution_candidate  결과가 비면 다음 후보로 넘어감
  - term_resolution_sql_errors     해석과 어긋난 SQL 을 검증 단계에서 잡음

USE_ROLE_RESOLUTION 이 꺼져 있으면 chat.py 가 이 모듈을 호출하지 않는다.
그 경우 파이프라인은 역할 해석 없는 일반 NL2SQL 로 동작한다.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from app.core.term_resolver import (
    ROLE_TERM_KPI_POLICIES,
    format_term_resolution_for_prompt,
)

_BASE_DIR = os.path.dirname(__file__)
_SCHEMA_PATH = os.path.join(_BASE_DIR, "../../data/mes_schema.json")
_SCHEMA_CACHE: dict[str, dict[str, Any]] | None = None

# 데모용 날짜 앵커 — DB 최신 데이터 기준일로 고정 (실제 운영 시 "'GETDATE()'" 으로 변경)
_DATE_ANCHOR = "'2026-05-22'"


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


def _columns_for_table(table: str) -> list[str]:
    schema = _load_schema()
    return [str(col.get("name", "")).upper() for col in schema.get(table.upper(), {}).get("columns", [])]


def _qualified_ref(table: str, alias: str, column: str) -> str:
    return f"{alias}.[{column}]"


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



def enforce_kpi_columns_in_sql(
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


def deterministic_sql_description(question: str, term_resolution: dict[str, Any]) -> str:
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


def patch_term_resolution_with_policy(
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


def build_deterministic_sql(
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


def advance_term_resolution_candidate(term_resolution: dict[str, Any] | None) -> dict[str, Any] | None:
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



def _sql_contains_column(sql: str, column_ref: str) -> bool:
    match = re.match(r"^\s*(CIM_[A-Z0-9_]+)\.([A-Z0-9_]+)\s*$", column_ref.upper())
    if not match:
        return False
    table, column = match.groups()
    upper_sql = sql.upper()
    return column in upper_sql and table in upper_sql


def term_resolution_sql_errors(sql: str, term_resolution: dict[str, Any] | None) -> list[str]:
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


