from __future__ import annotations

import difflib
import re

from app.schema import column_names
from app.sql_text import QUALIFIED_COL_RE, extract_cim_tables, table_aliases
from app.validation.query_safety import validate_query

# T-SQL: alias 는 WITH (NOLOCK) 앞
_RESERVED_AFTER_TABLE = (
    "ON",
    "WHERE",
    "INNER",
    "LEFT",
    "RIGHT",
    "FULL",
    "CROSS",
    "OUTER",
    "JOIN",
    "GROUP",
    "ORDER",
    "HAVING",
    "SELECT",
    "UNION",
    "AS",
)

_ALIAS_AFTER_HINT_RE = re.compile(
    r"\b(FROM|JOIN)\s+(?P<table>\[?[A-Za-z_][A-Za-z0-9_]*\]?)\s+"
    r"(?P<hint>WITH\s*\(\s*NOLOCK\s*\))\s+"
    r"(?P<alias>\[?[A-Za-z_][A-Za-z0-9_]*\]?)\b",
    re.IGNORECASE,
)

_QUOTED_ALIAS_RE = re.compile(r"\bAS\s+'([^']+)'", re.IGNORECASE)

_PARENS_TABLE_RE = re.compile(
    r"\b(FROM|JOIN)\s+\(\s*(?P<inner>\[?[A-Za-z_][A-Za-z0-9_]*\]?\s*"
    r"(?:WITH\s*\(\s*NOLOCK\s*\))?)\s*\)",
    re.IGNORECASE,
)

# T-SQL: 공백 포함 alias 는 대괄호 필요
_SPACED_ALIAS_RE = re.compile(
    r"\bAS\s+(?!\[|N?')(?P<alias>[^\s,()\[\]']+(?:[ \t]+[^\s,()\[\]']+)+?)"
    r"(?=\s*(?:,|\bFROM\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bJOIN\b|$))",
    re.IGNORECASE,
)

# 실제 MES API: DISTINCT 오류, COUNT(DISTINCT x) 제외
_LEADING_DISTINCT_RE = re.compile(r"^(\s*SELECT)\s+DISTINCT\s+(?!TOP\b)", re.IGNORECASE)


def _fix_alias_after_hint(sql: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        alias = m.group("alias")
        if alias.upper().strip("[]") in _RESERVED_AFTER_TABLE:
            return m.group(0)
        changed = True
        return f"{m.group(1)} {m.group('table')} {alias} {m.group('hint')}"

    for _ in range(10):
        new = _ALIAS_AFTER_HINT_RE.sub(repl, sql)
        if new == sql:
            break
        sql = new
    return sql, changed


def _fix_unknown_columns(sql: str) -> tuple[str, list]:
    schema = column_names()
    amap = {t: t for t in extract_cim_tables(sql)} | table_aliases(sql)
    fixed_notes = []

    def repl(m: re.Match) -> str:
        qual, col = m.group(1), m.group(2)
        table = amap.get(qual.upper())
        if not table or table not in schema:
            return m.group(0)
        cols = schema[table]
        if col.upper() in cols:
            return m.group(0)
        target = col.upper()
        contains = sorted(
            (c for c in cols if c.endswith(target) or target.endswith(c)),
            key=len,
        )
        near = contains[:1] or difflib.get_close_matches(target, sorted(cols), n=1, cutoff=0.72)
        if not near:
            return m.group(0)
        fixed_notes.append(f"{qual}.{col} -> {qual}.{near[0]}")
        return f"{qual}.{near[0]}"

    return QUALIFIED_COL_RE.sub(repl, sql), fixed_notes


def autofix_sql(sql: str) -> tuple[str, list[str]]:
    if not sql:
        return sql, []

    applied: list[str] = []

    fixed, changed = _fix_alias_after_hint(sql)
    if changed:
        applied.append("alias 를 WITH (NOLOCK) 앞으로 이동")
    sql = fixed

    # alias 를 붙인 테이블은 alias 로만 참조 가능
    for alias, table in table_aliases(sql).items():
        pattern = re.compile(rf"\b{table}\s*\.(?=\s*[A-Z_])", re.IGNORECASE)
        if pattern.search(sql):
            sql = pattern.sub(f"{alias}.", sql)
            applied.append(f"{table}. 을 alias {alias}. 로 변경")

    if _QUOTED_ALIAS_RE.search(sql):
        sql = _QUOTED_ALIAS_RE.sub(lambda m: f"AS {m.group(1)}", sql)
        applied.append("컬럼 alias 의 작은따옴표 제거")

    if _PARENS_TABLE_RE.search(sql):
        sql = _PARENS_TABLE_RE.sub(lambda m: f"{m.group(1)} {m.group('inner').strip()}", sql)
        applied.append("테이블을 감싼 괄호 제거")

    if _SPACED_ALIAS_RE.search(sql):
        sql = _SPACED_ALIAS_RE.sub(lambda m: f"AS [{m.group('alias').strip()}]", sql)
        applied.append("공백이 들어간 별칭을 대괄호로 감쌈")

    if _LEADING_DISTINCT_RE.search(sql):
        sql = _LEADING_DISTINCT_RE.sub(r"\1 TOP 1000 ", sql)
        applied.append("SELECT DISTINCT 를 SELECT TOP 1000 으로 대체")

    if validate_query(sql).risks == ["full_scan"]:
        sql = re.sub(r"^\s*SELECT\s+", "SELECT TOP 1000 ", sql, count=1, flags=re.IGNORECASE)
        applied.append("행 수 제한 없는 조회에 TOP 1000 추가")

    sql, col_notes = _fix_unknown_columns(sql)
    if col_notes:
        applied.append("스키마에 없는 컬럼 교정: " + ", ".join(col_notes))

    return sql, applied
