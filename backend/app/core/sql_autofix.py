"""생성된 SQL 의 기계적 오류를 자동 교정한다.

논문의 post-validation/auto-correction 단계에 해당한다. 재생성으로 고치면
LLM 호출이 한 번 더 드는데, 아래 오류들은 문법이 확정적이라 코드로 바로잡는
편이 싸고 확실하다.

`FROM CIM_LOT WITH(NOLOCK) L` 은 실제로 T-SQL 문법 오류다
(ODBC 42000: 'L' 근처의 구문이 잘못되었습니다). T-SQL 은 alias 가 테이블명
바로 뒤, 테이블 힌트보다 앞에 와야 한다. Qwen3.5-9B 는 프롬프트로 금지해도
이 형태를 반복해서 생성한다.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from functools import lru_cache

# FROM/JOIN <table> WITH (NOLOCK) <alias>  ->  FROM/JOIN <table> <alias> WITH (NOLOCK)
# alias 자리에 올 수 없는 예약어는 제외한다.
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

# AS '이름' -> AS 이름
_QUOTED_ALIAS_RE = re.compile(r"\bAS\s+'([^']+)'", re.IGNORECASE)

# 테이블을 괄호로 감싼 형태: FROM (CIM_LOT WITH(NOLOCK))
_PARENS_TABLE_RE = re.compile(
    r"\b(FROM|JOIN)\s+\(\s*(?P<inner>\[?[A-Za-z_][A-Za-z0-9_]*\]?\s*"
    r"(?:WITH\s*\(\s*NOLOCK\s*\))?)\s*\)",
    re.IGNORECASE,
)


# AS 뒤에 공백이 낀 별칭: AS LOT 건수  ->  AS [LOT 건수]
# T-SQL 은 공백이 있는 별칭을 대괄호나 따옴표로 감싸야 한다.
_SPACED_ALIAS_RE = re.compile(
    r"\bAS\s+(?!\[|N?')(?P<alias>[^\s,()\[\]']+(?:[ \t]+[^\s,()\[\]']+)+?)"
    r"(?=\s*(?:,|\bFROM\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bJOIN\b|$))",
    re.IGNORECASE,
)

# 선두 SELECT DISTINCT -> SELECT TOP 1000
# 일부 테이블에서 DISTINCT 가 DB 오류를 낸다. COUNT(DISTINCT x) 는 건드리지 않는다.
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

    # 한 번에 안 잡히는 연쇄 JOIN 을 위해 변화가 없을 때까지 반복
    for _ in range(10):
        new = _ALIAS_AFTER_HINT_RE.sub(repl, sql)
        if new == sql:
            break
        sql = new
    return sql, changed



# ── 스키마에 없는 컬럼 교정 ──────────────────────────────────────
# 모델이 그럴듯한 이름을 지어내는 경우가 남는다(예: NODENAME).
# 실제 스키마에 없으면 같은 테이블 안에서 가장 가까운 이름으로 바꾼다.

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../../data/mes_schema.json")


@lru_cache(maxsize=1)
def _schema_columns() -> dict:
    """{TABLE: {COLUMN, ...}} 와 전체 컬럼 집합."""
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    tables = data.get("tables", data)
    out: dict[str, set] = {}
    for t in tables:
        out[t["name"].upper()] = {c["name"].upper() for c in t.get("columns", [])}
    return out


_QUALIFIED_COL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")


def _resolve_alias_map(sql: str) -> dict:
    """SQL 안의 alias -> 실제 테이블 이름."""
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
        # NODENAME -> PROCESSNODENAME 처럼 접미사로 포함되는 경우를 먼저 본다.
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
    """교정된 SQL 과 적용한 교정 목록을 돌려준다."""
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
