"""
생성 SQL의 테이블·컬럼을 mes_schema.json 화이트리스트와 대조.

LLM 환각 테이블(예: CIM_MATERIAL)을 DB 실행 전에 차단하고 수정 힌트를 제공한다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from app.core.code_values import validate_code_literals
from app.core.concept_alignment import validate_concept_table_alignment

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMA_PATH = os.path.join(_BASE_DIR, "../../data/mes_schema.json")

CIM_TABLE_RE = re.compile(r"\b(CIM_[A-Z][A-Z0-9_]*)\b", re.IGNORECASE)
QUALIFIED_COL_RE = re.compile(
    r"\b(CIM_[A-Z][A-Z0-9_]*)\s*\.\s*([A-Z][A-Z0-9_]*)\b",
    re.IGNORECASE,
)
FROM_TABLE_RE = re.compile(
    r"\bFROM\s+(CIM_[A-Z][A-Z0-9_]*)\b",
    re.IGNORECASE,
)
SELECT_STAR_RE = re.compile(
    r"\bSELECT\s+(?:DISTINCT\s+)?\*|\.(\s*)?\*",
    re.IGNORECASE,
)

# SELECT DISTINCT without TOP — causes HTTP 500 on some MES tables
SELECT_DISTINCT_RE = re.compile(r"\bSELECT\s+DISTINCT\b(?!\s+TOP\b)", re.IGNORECASE)

# Single-quoted column aliases — not supported by MES API
SINGLE_QUOTE_ALIAS_RE = re.compile(r"\bAS\s+'[^']*'", re.IGNORECASE)

# alias placed after WITH(NOLOCK) — wrong order
NOLOCK_BEFORE_ALIAS_RE = re.compile(
    r"\bWITH\s*\(\s*NOLOCK\s*\)\s+(?!ON\b|WHERE\b|INNER\b|LEFT\b|RIGHT\b|JOIN\b|GROUP\b|ORDER\b|HAVING\b|SELECT\b)[A-Z][A-Z0-9]*\b",
    re.IGNORECASE,
)

NOLOCK_RE = re.compile(r"\bWITH\s*\(\s*NOLOCK\s*\)", re.IGNORECASE)

# 스키마에 없는 환각 컬럼 (단독 출현 시 차단, PROCESSNODENAME 등 정식명은 제외)
FORBIDDEN_COLUMNS: dict[str, str] = {
    "NODENAME": "PROCESSNODENAME 을 사용하세요.",
    "SEGMENTNAME": "PROCESSSEGMENTNAME 을 사용하세요.",
    "ORDERID": "PRODUCTORDERID 또는 WORKORDERID 를 사용하세요.",
    "SAFETYSTOCKYN": "CIM_MATERIALDEFINITION.SAFETY_QTY > 0 조건을 사용하세요.",
    "MATERIALID": "MATERIALDEFINITIONID 를 사용하세요.",
}
FORBIDDEN_COL_RE = re.compile(
    r"(?<![A-Z0-9_])(" + "|".join(FORBIDDEN_COLUMNS) + r")\b",
    re.IGNORECASE,
)

# LLM이 자주 만드는不存在 테이블 → 안내 문구
INVALID_TABLE_HINTS: dict[str, str] = {
    "CIM_MATERIAL": (
        "CIM_MATERIAL 테이블은 MES 스키마에 없습니다. "
        "자재 LOT·입고·수량 → CIM_MATERIALLOT, "
        "자재 정의·안전재고(SAFETY_QTY) → CIM_MATERIALDEFINITION 을 사용하세요."
    ),
    "CIM_EQUIPMENTSTATE": (
        "CIM_EQUIPMENTSTATE 테이블은 없습니다. 설비 상태는 CIM_EQUIPMENT 등 "
        "스키마에 정의된 테이블·컬럼을 사용하세요."
    ),
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
            parts.append(
                "존재하지 않는 테이블: " + ", ".join(self.invalid_tables)
            )
        if self.invalid_columns:
            cols = ", ".join(f"{t}.{c}" for t, c in self.invalid_columns)
            parts.append("존재하지 않는 컬럼: " + cols)
        if self.hints:
            parts.extend(self.hints)
        return " | ".join(parts) if parts else ""


class MesSchemaRegistry:
    def __init__(self, schema_path: str = DEFAULT_SCHEMA_PATH):
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        self.tables: dict[str, set[str]] = {}
        for t in data.get("tables", []):
            name = t["name"].upper()
            cols = {c["name"].upper() for c in t.get("columns", [])}
            self.tables[name] = cols

    @property
    def table_names(self) -> set[str]:
        return set(self.tables.keys())

    def has_table(self, name: str) -> bool:
        return name.upper() in self.tables

    def has_column(self, table: str, column: str) -> bool:
        cols = self.tables.get(table.upper())
        return cols is not None and column.upper() in cols


@lru_cache(maxsize=1)
def get_schema_registry(schema_path: str = DEFAULT_SCHEMA_PATH) -> MesSchemaRegistry:
    return MesSchemaRegistry(schema_path)


def extract_cim_tables(sql: str) -> set[str]:
    return {m.upper() for m in CIM_TABLE_RE.findall(sql)}


def extract_qualified_columns(sql: str) -> list[tuple[str, str]]:
    return [(t.upper(), c.upper()) for t, c in QUALIFIED_COL_RE.findall(sql)]


def _find_forbidden_columns(sql: str) -> list[str]:
    return sorted({m.upper() for m in FORBIDDEN_COL_RE.findall(sql)})


def _check_nolock(sql: str, tables: list[str]) -> Optional[str]:
    if not tables:
        return None
    if not NOLOCK_RE.search(sql):
        return "모든 CIM_* 테이블에 WITH (NOLOCK) 힌트가 필요합니다."
    return None


def _check_select_star(sql: str) -> Optional[str]:
    if SELECT_STAR_RE.search(sql):
        return "SELECT * 금지. 스키마에 있는 컬럼명을 명시하세요."
    return None


def _check_sql_syntax(sql: str) -> Optional[str]:
    upper = sql.upper()
    if re.search(r"ORDER\s+BYSUM", upper):
        return "ORDER BY SUM(...) 형식 오류. ORDER BY 와 SUM 사이에 공백이 필요합니다."
    if '""' in sql or re.search(r'"\s*\+\s*""', sql):
        return "SQL 문자열이 깨졌습니다. 완전한 단일 SELECT 문으로 다시 작성하세요."
    return None


def _check_invalid_fk_columns(
    sql: str, reg: MesSchemaRegistry
) -> list[tuple[str, str]]:
    """존재하지 않는 FK 컬럼 (예: CIM_BATCH.LOTID)."""
    bad: list[tuple[str, str]] = []
    for table, col in extract_qualified_columns(sql):
        if reg.has_table(table) and not reg.has_column(table, col):
            bad.append((table, col))
    return bad


def validate_sql(
    sql: str,
    *,
    question: Optional[str] = None,
    registry: Optional[MesSchemaRegistry] = None,
    check_columns: bool = True,
) -> ValidationResult:
    """
    SQL에 등장하는 CIM_* 테이블·CIM_테이블.컬럼 참조를 스키마와 대조.
    """
    if not sql or not sql.strip():
        return ValidationResult(ok=False, hints=["SQL이 비어 있습니다."])

    reg = registry or get_schema_registry()
    tables = sorted(extract_cim_tables(sql))
    invalid_tables = [t for t in tables if not reg.has_table(t)]

    invalid_columns: list[tuple[str, str]] = []
    if check_columns:
        invalid_columns = _check_invalid_fk_columns(sql, reg)

    hints: list[str] = []
    for t in invalid_tables:
        if t in INVALID_TABLE_HINTS:
            hints.append(INVALID_TABLE_HINTS[t])

    for col in _find_forbidden_columns(sql):
        hints.append(f"존재하지 않는 컬럼 {col}: {FORBIDDEN_COLUMNS[col]}")

    star_err = _check_select_star(sql)
    if star_err:
        hints.append(star_err)

    distinct_err: Optional[str] = None
    if SELECT_DISTINCT_RE.search(sql):
        distinct_err = "SELECT DISTINCT 금지. SELECT TOP 1000 또는 GROUP BY로 대체하세요."
        hints.append(distinct_err)

    quote_alias_err: Optional[str] = None
    if SINGLE_QUOTE_ALIAS_RE.search(sql):
        quote_alias_err = "컬럼 alias에 작은따옴표 사용 금지. AS '이름' → AS 이름 으로 수정하세요."
        hints.append(quote_alias_err)

    nolock_alias_err: Optional[str] = None
    if NOLOCK_BEFORE_ALIAS_RE.search(sql):
        nolock_alias_err = "테이블 alias는 WITH(NOLOCK) 앞에 위치해야 합니다. FROM TABLE alias WITH(NOLOCK) 형식 사용."
        hints.append(nolock_alias_err)

    nolock_err = _check_nolock(sql, tables)
    if nolock_err:
        hints.append(nolock_err)

    syntax_err = _check_sql_syntax(sql)
    if syntax_err:
        hints.append(syntax_err)

    code_vr = validate_code_literals(sql, referenced_tables=tables)
    if not code_vr.ok:
        hints.extend(code_vr.hints)

    align_ok = True
    if question:
        align_vr = validate_concept_table_alignment(question, sql)
        if not align_vr.ok:
            align_ok = False
            hints.extend(align_vr.hints)

    forbidden = _find_forbidden_columns(sql)
    ok = (
        not invalid_tables
        and not invalid_columns
        and not forbidden
        and not star_err
        and not distinct_err
        and not quote_alias_err
        and not nolock_alias_err
        and not nolock_err
        and not syntax_err
        and code_vr.ok
        and align_ok
    )
    return ValidationResult(
        ok=ok,
        invalid_tables=invalid_tables,
        invalid_columns=invalid_columns,
        hints=hints,
        referenced_tables=tables,
    )


def allowed_tables_hint(max_names: int = 30) -> str:
    """프롬프트에 넣을 짧은 화이트리스트 안내."""
    names = sorted(get_schema_registry().table_names)
    listed = ", ".join(names[:max_names])
    extra = len(names) - max_names
    suffix = f" 외 {extra}개" if extra > 0 else ""
    forbidden = (
        "\n- **CIM_MATERIAL 사용 금지** (스키마에 없음). "
        "자재 LOT → CIM_MATERIALLOT, 자재 정의·안전재고 → CIM_MATERIALDEFINITION"
    )
    return f"사용 가능한 테이블 예: {listed}{suffix}.{forbidden}"
