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

from app.core.code_values import code_values_prompt_hint, validate_code_literals
from app.core.concept_alignment import (
    alignment_prompt_rules,
    validate_concept_table_alignment,
)

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


def build_schema_correction_prompt(
    question: str,
    schema_ctx: str,
    invalid_sql: str,
    validation: ValidationResult,
) -> str:
    from core.concept_alignment import alignment_prompt_rules
    """스키마 오류 시 LLM 재생성용 프롬프트."""
    err = validation.error_message()
    valid_sample = ", ".join(sorted(get_schema_registry().table_names)[:12])
    cv = code_values_prompt_hint() or "(없음)"
    return f"""이전에 생성한 SQL에 스키마 오류가 있습니다. mes_schema.json에 정의된 이름만 사용해 다시 작성하세요.

## 오류 내용
{err}

## 잘못된 SQL
{invalid_sql}

## MES 스키마 정보
{schema_ctx}

## 허용 테이블 (일부)
{valid_sample} ... (총 {len(get_schema_registry().table_names)}개 CIM_* 테이블)

## 필수 규칙
- CIM_MATERIAL 테이블은 존재하지 않음. 자재 LOT → CIM_MATERIALLOT, 자재 정의·안전재고 → CIM_MATERIALDEFINITION
- 컬럼/테이블명은 스키마에 있는 이름만 사용
- SELECT만, 모든 테이블에 WITH (NOLOCK)
- SELECT * 금지. NODENAME/SEGMENTNAME/ORDERID/SAFETYSTOCKYN/MATERIALID 컬럼 금지
- 단일 테이블 목록 질의는 JOIN 하지 말 것. CIM_BATCH.LOTID 컬럼 없음 (LOT 연결은 CIM_LOTBATCHREL)
- 자재 LOT 이름 → MATERIALLOTNAME (LOTNAME은 CIM_LOT 전용)

## 코드값 (WHERE 절 리터럴)
{cv}

## 질의-테이블 매핑
{alignment_prompt_rules()}

## 사용자 질문
{question}

반드시 JSON만 응답: {{"sql": "SELECT ...", "description": "..."}}
JSON 응답:"""


def build_db_correction_prompt(
    question: str,
    schema_ctx: str,
    failed_sql: str,
    db_error: str,
) -> str:
    """DB 실행 실패 시 LLM 재생성용 프롬프트."""
    cv = code_values_prompt_hint() or "(없음)"
    return f"""이전 SQL은 스키마 검증은 통과했으나 MES DB 실행에 실패했습니다. 오류를 참고해 단순하고 실행 가능한 SELECT로 다시 작성하세요.

## DB 오류
{db_error[:500]}

## 실패한 SQL
{failed_sql}

## MES 스키마 정보
{schema_ctx}

## 수정 지침
- 불필요한 JOIN 제거. 단일 테이블로 가능하면 JOIN 하지 마세요.
- SELECT * 금지. WITH (NOLOCK) 모든 테이블에 적용.
- JOIN은 스키마 FK 관계만 사용 (CIM_BATCH.LOTID 같은 컬럼 없음).
- 복잡한 서브쿼리·DATEDIFF 계산 대신 스키마에 있는 컬럼을 직접 SELECT.

## 코드값
{cv}

## 질의-테이블 매핑
{alignment_prompt_rules()}

## 사용자 질문
{question}

반드시 JSON만 응답: {{"sql": "SELECT ...", "description": "..."}}
JSON 응답:"""


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


def full_validation_hint() -> str:
    parts = [allowed_tables_hint(), code_values_prompt_hint(), alignment_prompt_rules()]
    return "\n".join(p for p in parts if p)
