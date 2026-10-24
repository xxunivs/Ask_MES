from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CODE_VALUES_PATH = os.path.join(_BASE_DIR, "../../data/mes_code_values.json")
CODE_PROFILE_PATH = os.path.join(_BASE_DIR, "../../data/mes_code_profile.json")

DEFAULT_FORBIDDEN_YN = ["TRUE", "FALSE", "true", "false", "1", "0", "YES", "NO"]

LITERAL_EQ_RE = re.compile(
    r"\b(?:(?P<table>CIM_[A-Z][A-Z0-9_]*)\s*\.\s*)?(?P<column>[A-Z][A-Z0-9_]*)\s*=\s*'([^']*)'",
    re.IGNORECASE,
)
LITERAL_IN_RE = re.compile(
    r"\b(?:(?P<table>CIM_[A-Z][A-Z0-9_]*)\s*\.\s*)?(?P<column>[A-Z][A-Z0-9_]*)\s+IN\s*\(\s*([^)]+)\)",
    re.IGNORECASE,
)
LITERAL_EQ_NUM_RE = re.compile(
    r"\b(?:(?P<table>CIM_[A-Z][A-Z0-9_]*)\s*\.\s*)?(?P<column>[A-Z][A-Z0-9_]*)\s*=\s*(?P<num>\d+)\b",
    re.IGNORECASE,
)


@dataclass
class CodeColumnRule:
    key: str
    table: str
    column: str
    label: str
    values: set[str]
    forbidden_literals: set[str]
    forbid_numeric: bool = False

    def format_allowed(self, max_items: int = 12) -> str:
        vals = sorted(self.values)[:max_items]
        extra = len(self.values) - len(vals)
        s = ", ".join(f"'{v}'" for v in vals)
        if extra > 0:
            s += f" 외 {extra}개"
        return s


@dataclass
class CodeValidationResult:
    ok: bool
    invalid_literals: list[tuple[str, str, str]] = field(default_factory=list)
    """(key, used_literal, message)"""
    hints: list[str] = field(default_factory=list)


class CodeValuesRegistry:
    def __init__(self, path: str = CODE_VALUES_PATH):
        self.path = path
        self.rules: dict[str, CodeColumnRule] = {}
        self._load(path)

    def _load(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key, spec in (data.get("columns") or {}).items():
            if "." not in key:
                continue
            table, column = key.upper().split(".", 1)
            allowed = {str(v) for v in spec.get("values") or []}
            forbidden = {str(v) for v in spec.get("forbidden_literals") or []}
            if not forbidden and allowed <= {"Y", "N"}:
                forbidden = set(DEFAULT_FORBIDDEN_YN)
            forbid_num = spec.get("forbid_numeric")
            if forbid_num is None:
                forbid_num = allowed <= {"Y", "N"} and bool(allowed)
            self.rules[key.upper()] = CodeColumnRule(
                key=key.upper(),
                table=table,
                column=column,
                label=spec.get("label") or column,
                values=allowed,
                forbidden_literals=forbidden,
                forbid_numeric=bool(forbid_num),
            )

    def reload(self):
        self.rules.clear()
        self._load(self.path)

    def get_rule(self, table: str, column: str) -> Optional[CodeColumnRule]:
        return self.rules.get(f"{table.upper()}.{column.upper()}")

    def rules_by_column(self) -> dict[str, list[CodeColumnRule]]:
        out: dict[str, list[CodeColumnRule]] = {}
        for rule in self.rules.values():
            out.setdefault(rule.column, []).append(rule)
        return out


@lru_cache(maxsize=1)
def get_code_registry(path: str = CODE_VALUES_PATH) -> CodeValuesRegistry:
    return CodeValuesRegistry(path)


def _parse_in_list(raw: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"'([^']*)'", raw)]


def extract_column_literals(sql: str) -> list[tuple[Optional[str], str, str]]:
    found: list[tuple[Optional[str], str, str]] = []
    for m in LITERAL_EQ_RE.finditer(sql):
        t = m.group("table")
        table = t.upper() if t else None
        col = m.group("column").upper()
        found.append((table, col, m.group(3)))
    for m in LITERAL_IN_RE.finditer(sql):
        t = m.group("table")
        table = t.upper() if t else None
        col = m.group("column").upper()
        for lit in _parse_in_list(m.group(3)):
            found.append((table, col, lit))
    return found


def extract_numeric_equalities(sql: str) -> list[tuple[Optional[str], str, str]]:
    out = []
    for m in LITERAL_EQ_NUM_RE.finditer(sql):
        t = m.group("table")
        table = t.upper() if t else None
        out.append((table, m.group("column").upper(), m.group("num")))
    return out


def validate_code_literals(
    sql: str,
    *,
    referenced_tables: Optional[list[str]] = None,
    registry: Optional[CodeValuesRegistry] = None,
) -> CodeValidationResult:
    reg = registry or get_code_registry()
    if not reg.rules:
        return CodeValidationResult(ok=True)

    ref_tables = {t.upper() for t in (referenced_tables or [])}
    by_col = reg.rules_by_column()
    invalid: list[tuple[str, str, str]] = []
    hints: list[str] = []

    for table, col, literal in extract_column_literals(sql):
        candidates: list[CodeColumnRule] = []
        if table:
            rule = reg.get_rule(table, col)
            if rule:
                candidates = [rule]
        else:
            candidates = by_col.get(col, [])
            if ref_tables and len(candidates) > 1:
                candidates = [r for r in candidates if r.table in ref_tables] or candidates

        for rule in candidates:
            if not rule.values:
                continue
            lit_upper = literal.upper()
            allowed_upper = {v.upper() for v in rule.values}
            if lit_upper in allowed_upper:
                continue
            if literal in rule.forbidden_literals or lit_upper in {
                f.upper() for f in rule.forbidden_literals
            }:
                msg = (
                    f"{rule.key}: '{literal}' 사용 불가. "
                    f"허용 값: {rule.format_allowed()}"
                )
                invalid.append((rule.key, literal, msg))
                hints.append(msg)
            elif literal not in rule.values:
                msg = (
                    f"{rule.key}: '{literal}' 은(는) 수집된 코드값에 없음. "
                    f"허용: {rule.format_allowed()}"
                )
                invalid.append((rule.key, literal, msg))
                hints.append(msg)

    for table, col, num in extract_numeric_equalities(sql):
        candidates: list[CodeColumnRule] = []
        if table:
            rule = reg.get_rule(table, col)
            if rule:
                candidates = [rule]
        else:
            candidates = by_col.get(col, [])
            if ref_tables and len(candidates) > 1:
                candidates = [r for r in candidates if r.table in ref_tables] or candidates
        for rule in candidates:
            if not rule.forbid_numeric or not rule.values:
                continue
            msg = (
                f"{rule.key}: 숫자 {num} 사용 불가. "
                f"문자 코드값만 사용 (예: {rule.format_allowed()})"
            )
            invalid.append((rule.key, num, msg))
            hints.append(msg)

    seen = set()
    unique_hints = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            unique_hints.append(h)

    return CodeValidationResult(
        ok=not invalid,
        invalid_literals=invalid,
        hints=unique_hints,
    )


def code_values_prompt_hint(max_rules: int = 8) -> str:
    reg = get_code_registry()
    if not reg.rules:
        return ""
    lines = ["MES 컬럼 코드값 (DB DISTINCT 기준, WHERE 절에 그대로 사용):"]
    for i, rule in enumerate(sorted(reg.rules.values(), key=lambda r: r.key)):
        if i >= max_rules:
            lines.append(f"- … 외 {len(reg.rules) - max_rules}개 컬럼 (mes_code_values.json)")
            break
        forb = ", ".join(sorted(rule.forbidden_literals)[:6])
        lines.append(
            f"- {rule.key} ({rule.label}): 허용 {rule.format_allowed()}"
            + (f" | LLM 금지 예: {forb}" if forb else "")
        )
    return "\n".join(lines)


def rag_documents_for_code_values() -> list[tuple[str, str, dict]]:
    reg = get_code_registry()
    out = []
    for rule in reg.rules.values():
        if not rule.values:
            continue
        forb = ", ".join(sorted(rule.forbidden_literals))
        doc = (
            f"[코드값] {rule.key} ({rule.label})\n"
            f"허용 값: {rule.format_allowed()}\n"
            f"SQL 예: WHERE {rule.column} = '{next(iter(sorted(rule.values)))}'\n"
            f"금지 (LLM 환각): {forb or '없음'}"
        )
        out.append(
            (
                doc,
                f"code_{rule.table}_{rule.column}",
                {"type": "code_value", "table": rule.table, "column": rule.column},
            )
        )
    return out


def save_code_values(
    column_values: dict[str, dict],
    *,
    path: str = CODE_VALUES_PATH,
    source: str = "mes_api_distinct",
) -> str:
    payload = {
        "_comment": "scripts/collect_code_values.py 로 갱신",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "columns": column_values,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    get_code_registry.cache_clear()
    return path


def load_profile_columns(path: str = CODE_PROFILE_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("columns") or [])
