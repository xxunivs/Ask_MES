from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schema import has_column, has_table
from app.sql_text import QUALIFIED_COL_RE, extract_cim_tables, table_aliases
from app.validation.code_values import validate_code_literals
from app.validation.concept_alignment import validate_concept_table_alignment

# 없는 컬럼명: 대신 쓸 컬럼
FORBIDDEN_COLUMNS: dict[str, str] = {
    "NODENAME": "PROCESSNODENAME",
    "SEGMENTNAME": "PROCESSSEGMENTNAME",
    "ORDERID": "PRODUCTORDERID 또는 WORKORDERID",
    "SAFETYSTOCKYN": "CIM_MATERIALDEFINITION.SAFETY_QTY > 0 조건",
    "MATERIALID": "MATERIALDEFINITIONID",
}

INVALID_TABLE_HINTS: dict[str, str] = {
    "CIM_MATERIAL": (
        "CIM_MATERIAL 테이블은 없습니다. 자재 LOT, 입고, 수량은 CIM_MATERIALLOT, "
        "자재 정의, 안전재고(SAFETY_QTY)는 CIM_MATERIALDEFINITION 을 사용하세요."
    ),
    "CIM_EQUIPMENTSTATE": "CIM_EQUIPMENTSTATE 테이블은 없습니다. 설비 상태는 CIM_EQUIPMENT 를 사용하세요.",
}

_FORBIDDEN_COL_RE = re.compile(r"(?<![A-Z0-9_])(" + "|".join(FORBIDDEN_COLUMNS) + r")\b", re.IGNORECASE)
_SELECT_STAR_RE = re.compile(r"\bSELECT\s+(?:DISTINCT\s+)?\*|\.(\s*)?\*", re.IGNORECASE)
# 실제 MES API: TOP 없는 DISTINCT 시 HTTP 500
_SELECT_DISTINCT_RE = re.compile(r"\bSELECT\s+DISTINCT\b(?!\s+TOP\b)", re.IGNORECASE)
# 실제 MES API: 작은따옴표 alias 미지원
_SINGLE_QUOTE_ALIAS_RE = re.compile(r"\bAS\s+'[^']*'", re.IGNORECASE)
_NOLOCK_BEFORE_ALIAS_RE = re.compile(
    r"\bWITH\s*\(\s*NOLOCK\s*\)\s+(?!ON\b|WHERE\b|INNER\b|LEFT\b|RIGHT\b|JOIN\b|GROUP\b|ORDER\b|HAVING\b|SELECT\b)[A-Z][A-Z0-9]*\b",
    re.IGNORECASE,
)
_NOLOCK_RE = re.compile(r"\bWITH\s*\(\s*NOLOCK\s*\)", re.IGNORECASE)
_SUBQUERY_RE = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)
_CTE_RE = re.compile(r"\s*WITH\b", re.IGNORECASE)

# 컬럼이 아닌 단어: 키워드, 자료형, 날짜 단위
_SQL_WORDS = {
    "SELECT",
    "TOP",
    "FROM",
    "WHERE",
    "GROUP",
    "BY",
    "ORDER",
    "ASC",
    "DESC",
    "AND",
    "OR",
    "NOT",
    "NULL",
    "IS",
    "IN",
    "LIKE",
    "BETWEEN",
    "AS",
    "WITH",
    "NOLOCK",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "HAVING",
    "DISTINCT",
    "ON",
    "EXISTS",
    "ALL",
    "ANY",
    "TRUE",
    "FALSE",
    "PERCENT",
    "TIES",
    "OVER",
    "PARTITION",
    "ROWS",
    "UNBOUNDED",
    "PRECEDING",
    "FOLLOWING",
    "CURRENT",
    "ROW",
    "OFFSET",
    "FETCH",
    "NEXT",
    "FIRST",
    "ONLY",
    "DATE",
    "DATETIME",
    "DATETIME2",
    "SMALLDATETIME",
    "TIME",
    "CHAR",
    "VARCHAR",
    "NCHAR",
    "NVARCHAR",
    "TEXT",
    "INT",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "FLOAT",
    "REAL",
    "DECIMAL",
    "NUMERIC",
    "BIT",
    "MONEY",
    "MAX",
    "YEAR",
    "YY",
    "YYYY",
    "QUARTER",
    "QQ",
    "MONTH",
    "MM",
    "M",
    "WEEK",
    "WK",
    "WW",
    "DAY",
    "DD",
    "D",
    "DAYOFYEAR",
    "DY",
    "Y",
    "WEEKDAY",
    "DW",
    "HOUR",
    "HH",
    "MINUTE",
    "MI",
    "N",
    "SECOND",
    "SS",
    "S",
}


@dataclass
class ValidationResult:
    ok: bool
    invalid_tables: list[str] = field(default_factory=list)
    invalid_columns: list[tuple[str, str]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    referenced_tables: list[str] = field(default_factory=list)

    def error_message(self) -> str:
        parts = []
        if self.invalid_tables:
            parts.append("존재하지 않는 테이블: " + ", ".join(self.invalid_tables))
        if self.invalid_columns:
            parts.append("존재하지 않는 컬럼: " + ", ".join(f"{t}.{c}" for t, c in self.invalid_columns))
        parts.extend(self.hints)
        return " | ".join(parts)


def _is_simple_select(sql: str) -> bool:
    return not _SUBQUERY_RE.search(sql) and not _CTE_RE.match(sql)


def _invalid_qualified_columns(sql: str) -> list[tuple[str, str]]:
    aliases = table_aliases(sql)
    bad: list[tuple[str, str]] = []
    for qualifier, col in QUALIFIED_COL_RE.findall(sql):
        qualifier, col = qualifier.upper(), col.upper()
        table = qualifier if qualifier.startswith("CIM_") else aliases.get(qualifier)
        if table and has_table(table) and not has_column(table, col) and (table, col) not in bad:
            bad.append((table, col))
    return bad


# 단일 테이블 단순 SELECT 한정
def _unknown_bare_columns(sql: str) -> list[tuple[str, str]]:
    if not _is_simple_select(sql) or re.search(r"\bJOIN\b|\bUNION\b", sql, re.IGNORECASE):
        return []
    tables = [t for t in extract_cim_tables(sql) if has_table(t)]
    if len(tables) != 1:
        return []
    table = tables[0]
    body = re.sub(r"'[^']*'", "''", sql)
    body = re.sub(r"\[[^\]]*\]", "", body)
    known = _SQL_WORDS | {table} | set(table_aliases(body))
    known |= {a.upper() for a in re.findall(r"\bAS\s+([^\s,()]+)", body, re.IGNORECASE)}
    bad: list[tuple[str, str]] = []
    for m in re.finditer(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)(?![\w.])", body):
        word = m.group(1).upper()
        if word in known or not word.isascii() or re.match(r"\s*\(", body[m.end() :]):
            continue
        if not has_column(table, word) and (table, word) not in bad:
            bad.append((table, word))
    return bad


# 서브쿼리, CTE 제외
def _undefined_aliases(sql: str) -> list[str]:
    aliases = table_aliases(sql)
    if not aliases or not _is_simple_select(sql):
        return []
    known = set(aliases) | extract_cim_tables(sql)
    found: list[str] = []
    for qualifier, col in QUALIFIED_COL_RE.findall(sql):
        qualifier = qualifier.upper()
        if qualifier not in known and not col.upper().startswith("CIM_") and qualifier not in found:
            found.append(qualifier)
    return found


def _style_errors(sql: str, tables: list[str]) -> list[str]:
    errors: list[str] = []
    for col in sorted({m.upper() for m in _FORBIDDEN_COL_RE.findall(sql)}):
        errors.append(f"존재하지 않는 컬럼 {col}: {FORBIDDEN_COLUMNS[col]} 을(를) 사용하세요.")
    undefined = _undefined_aliases(sql)
    if undefined:
        errors.append(
            f"정의되지 않은 테이블 alias: {', '.join(undefined)}. FROM, JOIN 에서 지정한 alias 만 사용하세요."
        )
    if _SELECT_STAR_RE.search(sql):
        errors.append("SELECT * 금지. 컬럼명을 명시하세요.")
    if _SELECT_DISTINCT_RE.search(sql):
        errors.append("SELECT DISTINCT 금지. SELECT TOP 1000 또는 GROUP BY 를 사용하세요.")
    if _SINGLE_QUOTE_ALIAS_RE.search(sql):
        errors.append("컬럼 alias에 작은따옴표 금지. AS '이름' 대신 AS 이름 을 사용하세요.")
    if _NOLOCK_BEFORE_ALIAS_RE.search(sql):
        errors.append("테이블 alias는 WITH(NOLOCK) 앞에 둡니다. FROM 테이블 alias WITH(NOLOCK) 형식을 사용하세요.")
    if tables and not _NOLOCK_RE.search(sql):
        errors.append("모든 CIM_* 테이블에 WITH (NOLOCK) 이 필요합니다.")
    if re.search(r"ORDER\s+BYSUM", sql, re.IGNORECASE):
        errors.append("ORDER BY 와 SUM 사이에 공백이 필요합니다.")
    if '""' in sql or re.search(r'"\s*\+\s*""', sql):
        errors.append("SQL 문자열이 깨졌습니다. 완전한 단일 SELECT 문으로 다시 작성하세요.")
    return errors


def validate_sql(sql: str, *, question: str | None = None) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(ok=False, hints=["SQL이 비어 있습니다."])

    tables = sorted(extract_cim_tables(sql))
    invalid_tables = [t for t in tables if not has_table(t)]
    invalid_columns = _invalid_qualified_columns(sql)
    invalid_columns += [c for c in _unknown_bare_columns(sql) if c not in invalid_columns]

    errors = _style_errors(sql, tables)
    errors += validate_code_literals(sql, referenced_tables=tables).hints
    if question:
        errors += validate_concept_table_alignment(question, sql).hints

    table_notes = [INVALID_TABLE_HINTS[t] for t in invalid_tables if t in INVALID_TABLE_HINTS]
    return ValidationResult(
        ok=not invalid_tables and not invalid_columns and not errors,
        invalid_tables=invalid_tables,
        invalid_columns=invalid_columns,
        hints=table_notes + errors,
        referenced_tables=tables,
    )
