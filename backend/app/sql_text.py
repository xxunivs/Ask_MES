from __future__ import annotations

import re

CIM_TABLE_RE = re.compile(r"\b(CIM_[A-Z][A-Z0-9_]*)\b", re.IGNORECASE)
QUALIFIED_COL_RE = re.compile(r"\b([A-Z_][A-Z0-9_]*)\s*\.\s*([A-Z_][A-Z0-9_]*)\b", re.IGNORECASE)
_TABLE_ALIAS_RE = re.compile(
    r"(?:\bFROM|\bJOIN|,)\s*(CIM_[A-Z][A-Z0-9_]*)\s+(?:AS\s+)?([A-Z][A-Z0-9_]*)\b",
    re.IGNORECASE,
)
# FROM 테이블 뒤에 오는 키워드 (alias 아님)
_NOT_ALIAS = {
    "WITH",
    "ON",
    "WHERE",
    "JOIN",
    "INNER",
    "LEFT",
    "RIGHT",
    "FULL",
    "CROSS",
    "OUTER",
    "GROUP",
    "ORDER",
    "HAVING",
    "UNION",
    "SELECT",
    "AS",
}


def extract_cim_tables(sql: str) -> set[str]:
    return {m.upper() for m in CIM_TABLE_RE.findall(sql)}


def table_aliases(sql: str) -> dict[str, str]:
    return {
        alias.upper(): table.upper() for table, alias in _TABLE_ALIAS_RE.findall(sql) if alias.upper() not in _NOT_ALIAS
    }
