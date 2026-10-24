from __future__ import annotations

import difflib
import json
import os
import re
from functools import lru_cache

# T-SQL 은 alias 가 WITH (NOLOCK) 앞에 와야 함, 프롬프트로 금지해도 모델이 반복 생성
_RESERVED_AFTER_TABLE = (
    "ON", "WHERE", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "OUTER",
    "JOIN", "GROUP", "ORDER", "HAVING", "SELECT", "UNION", "AS",
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


# T-SQL 은 공백 포함 별칭에 대괄호나 따옴표 필요
_SPACED_ALIAS_RE = re.compile(
    r"\bAS\s+(?!\[|N?')(?P<alias>[^\s,()\[\]']+(?:[ \t]+[^\s,()\[\]']+)+?)"
    r"(?=\s*(?:,|\bFROM\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bJOIN\b|$))",
    re.IGNORECASE,
)

# 일부 테이블에서 DISTINCT 가 DB 오류 유발, COUNT(DISTINCT x) 는 대상 아님
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


_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../../data/mes_schema.json")


@lru_cache(maxsize=1)
def _schema_columns() -> dict:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    tables = data.get("tables", data)
    out: dict[str, set] = {}
    for t in tables:
        out[t["name"].upper()] = {c["name"].upper() for c in t.get("columns", [])}
    return out


_QUALIFIED_COL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")


def _resolve_alias_map(sql: str) -> dict:
    amap = {}
    for m in re.finditer(
        r"\b(?:FROM|JOIN)\s+(?P<table>CIM_[A-Za-z0-9_]+)(?:\s+(?:AS\s+)?(?P<alias>(?!WITH\b)[A-Za-z_][A-Za-z0-9_]*))?",
        sql, re.IGNORECASE,
    ):
        table = m.group("table").upper()
        amap[table] = table
        alias = m.group("alias")
        if alias:
            amap[alias.upper()] = table
    return amap


def _fix_unknown_columns(sql: str) -> tuple[str, list]:
    schema = _schema_columns()
    amap = _resolve_alias_map(sql)
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
        near = contains[:1] or difflib.get_close_matches(
            target, sorted(cols), n=1, cutoff=0.72
        )
        if not near:
            return m.group(0)
        fixed_notes.append(f"{qual}.{col} -> {qual}.{near[0]}")
        return f"{qual}.{near[0]}"

    return _QUALIFIED_COL_RE.sub(repl, sql), fixed_notes

def autofix_sql(sql: str) -> tuple[str, list[str]]:
    if not sql:
        return sql, []

    applied: list[str] = []

    fixed, changed = _fix_alias_after_hint(sql)
    if changed:
        applied.append("alias 를 WITH (NOLOCK) 앞으로 이동")
    sql = fixed

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

    sql, col_notes = _fix_unknown_columns(sql)
    if col_notes:
        applied.append("스키마에 없는 컬럼 교정: " + ", ".join(col_notes))

    return sql, applied
