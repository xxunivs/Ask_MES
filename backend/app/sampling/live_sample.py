from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from app.execution.sql_executor import execute_sql
from app.schema import tables_by_name

_LIVE_CONTEXT_CACHE: dict[tuple[str, ...], tuple[float, str]] = {}
_LIVE_CONTEXT_TTL = 60.0

DATE_HINTS = ("TIME", "DATE")
VALUE_HINTS = (
    "STATE",
    "TYPE",
    "ID",
    "NAME",
    "PROCESS",
    "EQUIPMENT",
    "DEFECT",
    "USER",
    "SITE",
)


def extract_context_tables(schema_context: str, max_tables: int = 4) -> list[str]:
    schema = tables_by_name()
    found: list[str] = []

    for match in re.finditer(r"관련 테이블:\s*([A-Z0-9_,\s]+)", schema_context):
        for table in re.findall(r"CIM_\w+", match.group(1)):
            if table in schema and table not in found:
                found.append(table)
                if len(found) >= max_tables:
                    return found

    patterns = [
        r"\[테이블\]\s+(CIM_\w+)",
        r"(?:FROM|JOIN)\s+(CIM_\w+)\s+WITH",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, schema_context):
            table = match.group(1)
            if table in schema and table not in found:
                found.append(table)
                if len(found) >= max_tables:
                    return found

    return found


# 값 분포 조회 제외 (값 종류가 많은 컬럼)
_HIGH_CARDINALITY_SUFFIXES = ("ID", "NAME", "DESCRIPTION", "COMMENT", "TEXT")
_TEXT_TYPES = ("char", "varchar", "nvarchar", "nchar")


def _column_type(table: str, column: str) -> str:
    for col in _table_columns(table):
        if col.get("name") == column:
            return str(col.get("type", "")).lower()
    return ""


def extract_value_columns(schema_context: str, max_cols: int = 4) -> list[tuple[str, str]]:
    schema = tables_by_name()
    found: list[tuple[str, str]] = []

    def add(table: str, column: str) -> None:
        if table in schema and (table, column) not in found and len(found) < max_cols:
            if _column_type(table, column).startswith(_TEXT_TYPES):
                found.append((table, column))

    for match in re.finditer(r"관련 컬럼:\s*([A-Z0-9_.,\s]+)", schema_context):
        for table, column in re.findall(r"(CIM_\w+)\.(\w+)", match.group(1)):
            add(table, column)
    for table, column in re.findall(r"\[컬럼\]\s+(CIM_\w+)\.(\w+)", schema_context):
        if not column.upper().endswith(_HIGH_CARDINALITY_SUFFIXES):
            add(table, column)
    return found


def _quote_col(column: str) -> str:
    return f"[{column}]"


def _table_columns(table: str) -> list[dict[str, Any]]:
    return tables_by_name().get(table, {}).get("columns", [])


def _choose_sample_columns(table: str, max_cols: int = 8) -> list[str]:
    info = tables_by_name().get(table, {})
    columns = _table_columns(table)
    names = [c.get("name", "") for c in columns if c.get("name")]
    chosen: list[str] = []

    for name in info.get("pk", []):
        if name in names and name not in chosen:
            chosen.append(name)

    for hint in ("LASTEVENTTIME", "TRACKINTIME", "CREATEDTIME", "DELIVERYDATE", "DUEDATE"):
        if hint in names and hint not in chosen:
            chosen.append(hint)

    for name in names:
        upper = name.upper()
        if any(token in upper for token in VALUE_HINTS) and name not in chosen:
            chosen.append(name)
        if len(chosen) >= max_cols:
            return chosen[:max_cols]

    for name in names:
        if name not in chosen:
            chosen.append(name)
        if len(chosen) >= max_cols:
            break

    return chosen[:max_cols]


def _date_columns(table: str, max_cols: int = 2) -> list[str]:
    cols: list[str] = []
    for col in _table_columns(table):
        name = col.get("name", "")
        ctype = str(col.get("type", "")).lower()
        upper = name.upper()
        if "date" in ctype or "time" in ctype or any(hint in upper for hint in DATE_HINTS):
            cols.append(name)
        if len(cols) >= max_cols:
            break
    return cols


def _format_rows(result: dict[str, Any], max_rows: int = 3) -> str:
    rows = result.get("rows", []) or []
    columns = result.get("columns", []) or []
    if not rows:
        return "(rows 없음)"

    lines: list[str] = []
    for row in rows[:max_rows]:
        if isinstance(row, dict):
            pairs = [f"{col}={row.get(col)}" for col in columns[:8]]
        else:
            pairs = [str(value) for value in row[:8]]
        lines.append(", ".join(pairs))
    return " / ".join(lines)


def _format_values(result: dict[str, Any], column: str) -> str:
    rows = result.get("rows", []) or []
    if not rows:
        return "(값 없음)"
    return ", ".join(f"'{row.get(column)}'({row.get('건수')}건)" for row in rows)


async def build_live_db_context(schema_context: str, max_tables: int = 3) -> str:
    value_cols = extract_value_columns(schema_context)
    tables = extract_context_tables(schema_context, max_tables=max_tables)
    for table, _ in value_cols:
        if table not in tables:
            tables.append(table)
    if not tables:
        return ""
    cache_key = tuple(tables) + tuple(f"{t}.{c}" for t, c in value_cols)
    cached = _LIVE_CONTEXT_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _LIVE_CONTEXT_TTL:
        return cached[1]

    async def probe_table(table: str) -> str:
        lines = [f"### {table}"]
        probes: list[tuple[str, Any]] = []

        sample_cols = _choose_sample_columns(table)
        if sample_cols:
            col_sql = ", ".join(_quote_col(col) for col in sample_cols)
            sql = f"SELECT TOP 3 {col_sql} FROM {table} WITH (NOLOCK)"
            probes.append(("sample", execute_sql(sql, limit=3)))

        date_cols = _date_columns(table)
        if date_cols:
            exprs = []
            for col in date_cols:
                exprs.append(f"MIN({_quote_col(col)}) AS [{col}_MIN]")
                exprs.append(f"MAX({_quote_col(col)}) AS [{col}_MAX]")
            sql = f"SELECT {', '.join(exprs)} FROM {table} WITH (NOLOCK)"
            probes.append(("date", execute_sql(sql, limit=1)))

        for _, value_col in (vc for vc in value_cols if vc[0] == table):
            col = _quote_col(value_col)
            sql = (
                f"SELECT TOP 5 {col} AS [{value_col}], COUNT(*) AS [건수] "
                f"FROM {table} WITH (NOLOCK) "
                f"WHERE {col} IS NOT NULL AND CONVERT(nvarchar(200), {col}) <> '' "
                f"GROUP BY {col} ORDER BY [건수] DESC"
            )
            probes.append((value_col, execute_sql(sql, limit=5)))

        results = await asyncio.gather(
            *(probe for _, probe in probes),
            return_exceptions=True,
        )
        for (kind, _), result in zip(probes, results, strict=True):
            if isinstance(result, Exception):
                label = "샘플" if kind == "sample" else "날짜범위" if kind == "date" else f"{table}.{kind} 값"
                lines.append(f"- {label} 조회 실패: {result}")
            elif kind == "sample":
                lines.append(f"- 샘플: {_format_rows(result, max_rows=3)}")
            elif kind == "date":
                lines.append(f"- 날짜범위: {_format_rows(result, max_rows=1)}")
            else:
                lines.append(f"- {table}.{kind} 에 들어 있는 값: {_format_values(result, kind)}")
        return "\n".join(lines)

    sections = await asyncio.gather(*(probe_table(table) for table in tables))
    context = "\n\n".join(sections)
    _LIVE_CONTEXT_CACHE[cache_key] = (time.monotonic(), context)
    return context
