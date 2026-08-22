"""
Generate compact live-DB context for SQL generation.

The retriever tells the LLM which tables are likely relevant. This module
checks those tables against the real MES API with small, read-only probes.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

from app.core.sql_executor import execute_sql

_BASE_DIR = os.path.dirname(__file__)
SCHEMA_PATH = os.path.join(_BASE_DIR, "../../data/mes_schema.json")

_SCHEMA_CACHE: dict[str, dict[str, Any]] | None = None
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


def _load_schema() -> dict[str, dict[str, Any]]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    tables: dict[str, dict[str, Any]] = {}
    for table in raw.get("tables", []):
        name = table.get("name", "")
        if not name:
            continue
        tables[name] = {
            "description": table.get("description", ""),
            "columns": table.get("columns", []),
            "pk": table.get("pk", []),
        }

    _SCHEMA_CACHE = tables
    return tables


def extract_context_tables(schema_context: str, max_tables: int = 4) -> list[str]:
    """Extract table names mentioned in retriever context, preserving order."""
    schema = _load_schema()
    found: list[str] = []

    for match in re.finditer(r"관련 테이블:\s*([A-Z0-9_,\s]+)", schema_context):
        for table in re.findall(r"CIM_\w+", match.group(1)):
            if table in schema and table not in found:
                found.append(table)
                if len(found) >= max_tables:
                    return found

    patterns = [
        r"\[테이블\]\s+(CIM_\w+)",
        r"\[컬럼\]\s+(CIM_\w+)\.",
        r"(?:FROM|JOIN)\s+(CIM_\w+)\s+WITH",
        r"\b(CIM_\w+)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, schema_context):
            table = match.group(1)
            if table in schema and table not in found:
                found.append(table)
                if len(found) >= max_tables:
                    return found

    return found


def validate_sql_against_schema(sql: str) -> list[str]:
    """
    Lightweight guard against hallucinated tables/columns before hitting MES DB.

    It intentionally focuses on the most common LLM failure pattern:
    table aliases with non-existent column names, e.g. L.LOTQTY.
    """
    schema = _load_schema()
    errors: list[str] = []
    aliases: dict[str, str] = {}

    table_patterns = [
        re.compile(
            r"\b(?:FROM|JOIN)\s+(CIM_\w+)\s+WITH\s*\(NOLOCK\)\s*(?:AS\s+)?([A-Za-z_]\w*)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:FROM|JOIN)\s+(CIM_\w+)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?",
            re.IGNORECASE,
        ),
    ]

    for table_pattern in table_patterns:
        for match in table_pattern.finditer(sql):
            table = match.group(1).upper()
            alias = match.group(2) or table

            if table not in schema:
                error = f"스키마에 없는 테이블: {table}"
                if error not in errors:
                    errors.append(error)
                continue

            aliases[table] = table
            if alias and alias.upper() not in {"WITH", "ON", "WHERE", "JOIN", "GROUP", "ORDER"}:
                aliases[alias.upper()] = table

    for alias, column in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", sql):
        table = aliases.get(alias.upper())
        if not table:
            continue
        valid_columns = {c.get("name", "").upper() for c in schema[table].get("columns", [])}
        if column.upper() not in valid_columns:
            error = f"{table}에 없는 컬럼: {alias}.{column}"
            if error not in errors:
                errors.append(error)

    return errors


def _quote_col(column: str) -> str:
    return f"[{column}]"


def _table_columns(table: str) -> list[dict[str, Any]]:
    return _load_schema().get(table, {}).get("columns", [])


def _choose_sample_columns(table: str, max_cols: int = 8) -> list[str]:
    info = _load_schema().get(table, {})
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


def _value_column(table: str) -> str | None:
    preferred = (
        "PROCESSSEGMENTID",
        "PROCESSNODEID",
        "EQUIPMENTID",
        "DEFECTID",
        "DEFECTTYPE",
        "STATE",
        "PRODUCTID",
        "TRACKOUTUSER",
        "TRACKOUTUSERNAME",
    )
    names = [c.get("name", "") for c in _table_columns(table)]
    for name in preferred:
        if name in names:
            return name
    for name in names:
        upper = name.upper()
        if any(token in upper for token in VALUE_HINTS):
            return name
    return None


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


async def build_live_db_context(schema_context: str, max_tables: int = 3) -> str:
    """
    Probe the real MES DB with tiny SELECT queries and return compact context.

    Each probe is best-effort. Failures are included as hints instead of raising,
    so SQL generation can continue even when one table is unavailable.
    """
    tables = extract_context_tables(schema_context, max_tables=max_tables)
    if not tables:
        return ""
    cache_key = tuple(tables)
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

        value_col = _value_column(table)
        if value_col:
            col = _quote_col(value_col)
            sql = (
                f"SELECT TOP 5 {col} AS [{value_col}], COUNT(*) AS [건수] "
                f"FROM {table} WITH (NOLOCK) "
                f"WHERE {col} IS NOT NULL AND CONVERT(nvarchar(200), {col}) <> '' "
                f"GROUP BY {col} ORDER BY [건수] DESC"
            )
            probes.append(("value", execute_sql(sql, limit=5)))

        results = await asyncio.gather(
            *(probe for _, probe in probes),
            return_exceptions=True,
        )
        for (kind, _), result in zip(probes, results):
            if isinstance(result, Exception):
                label = "샘플" if kind == "sample" else "날짜범위" if kind == "date" else f"주요값({value_col})"
                lines.append(f"- {label} 조회 실패: {result}")
            elif kind == "sample":
                lines.append(f"- 샘플: {_format_rows(result, max_rows=3)}")
            elif kind == "date":
                lines.append(f"- 날짜범위: {_format_rows(result, max_rows=1)}")
            else:
                lines.append(f"- 주요값({value_col}): {_format_rows(result, max_rows=5)}")
        return "\n".join(lines)

    sections = await asyncio.gather(*(probe_table(table) for table in tables))
    context = "\n\n".join(sections)
    _LIVE_CONTEXT_CACHE[cache_key] = (time.monotonic(), context)
    return context
