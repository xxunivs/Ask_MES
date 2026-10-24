from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR

CODE_VALUES_PATH = DATA_DIR / "mes_code_values.json"
CODE_PROFILE_PATH = DATA_DIR / "mes_code_profile.json"

DEFAULT_FORBIDDEN_YN = ["TRUE", "FALSE", "true", "false", "1", "0", "YES", "NO"]

_COLUMN = r"\b(?:(?P<table>CIM_[A-Z][A-Z0-9_]*)\s*\.\s*)?(?P<column>[A-Z][A-Z0-9_]*)"
_LITERAL_EQ_RE = re.compile(_COLUMN + r"\s*=\s*'(?P<value>[^']*)'", re.IGNORECASE)
_LITERAL_IN_RE = re.compile(_COLUMN + r"\s+IN\s*\(\s*(?P<value>[^)]+)\)", re.IGNORECASE)
_NUMBER_EQ_RE = re.compile(_COLUMN + r"\s*=\s*(?P<value>\d+)\b", re.IGNORECASE)


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
        text = ", ".join(f"'{v}'" for v in vals)
        extra = len(self.values) - len(vals)
        return f"{text} 외 {extra}개" if extra > 0 else text


@dataclass
class CodeValidationResult:
    ok: bool
    # (컬럼 키, 쓴 값, 메시지)
    invalid_literals: list[tuple[str, str, str]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


class CodeValuesRegistry:
    def __init__(self, path: Path = CODE_VALUES_PATH):
        self.rules: dict[str, CodeColumnRule] = {}
        if path.exists():
            self._load(json.loads(path.read_text(encoding="utf-8")))

    def _load(self, data: dict) -> None:
        for key, spec in (data.get("columns") or {}).items():
            if "." not in key:
                continue
            key = key.upper()
            table, column = key.split(".", 1)
            allowed = {str(v) for v in spec.get("values") or []}
            is_yn = bool(allowed) and allowed <= {"Y", "N"}
            forbidden = {str(v) for v in spec.get("forbidden_literals") or []}
            if not forbidden and is_yn:
                forbidden = set(DEFAULT_FORBIDDEN_YN)
            forbid_numeric = spec.get("forbid_numeric")
            self.rules[key] = CodeColumnRule(
                key=key,
                table=table,
                column=column,
                label=spec.get("label") or column,
                values=allowed,
                forbidden_literals=forbidden,
                forbid_numeric=is_yn if forbid_numeric is None else bool(forbid_numeric),
            )

    def rules_for(self, table: str | None, column: str, referenced_tables: set[str]) -> list[CodeColumnRule]:
        if table:
            rule = self.rules.get(f"{table}.{column}")
            return [rule] if rule else []
        candidates = [r for r in self.rules.values() if r.column == column]
        if len(candidates) > 1 and referenced_tables:
            candidates = [r for r in candidates if r.table in referenced_tables] or candidates
        return candidates


@lru_cache(maxsize=1)
def get_code_registry() -> CodeValuesRegistry:
    return CodeValuesRegistry()


def _literals(sql: str) -> list[tuple[str | None, str, str]]:
    found = []
    for m in _LITERAL_EQ_RE.finditer(sql):
        found.append((m["table"], m["column"], m["value"]))
    for m in _LITERAL_IN_RE.finditer(sql):
        found += [(m["table"], m["column"], v) for v in re.findall(r"'([^']*)'", m["value"])]
    return [((t or "").upper() or None, c.upper(), v) for t, c, v in found]


def validate_code_literals(sql: str, *, referenced_tables: list[str] | None = None) -> CodeValidationResult:
    reg = get_code_registry()
    if not reg.rules:
        return CodeValidationResult(ok=True)

    tables = {t.upper() for t in referenced_tables or []}
    invalid: list[tuple[str, str, str]] = []

    for table, column, literal in _literals(sql):
        for rule in reg.rules_for(table, column, tables):
            if rule.values and literal.upper() not in {v.upper() for v in rule.values}:
                msg = f"{rule.key}: '{literal}' 은(는) 허용 값이 아닙니다. 허용: {rule.format_allowed()}"
                invalid.append((rule.key, literal, msg))

    for m in _NUMBER_EQ_RE.finditer(sql):
        table = (m["table"] or "").upper() or None
        for rule in reg.rules_for(table, m["column"].upper(), tables):
            if rule.forbid_numeric and rule.values:
                msg = f"{rule.key}: 숫자 {m['value']} 사용 불가. 문자 코드값 {rule.format_allowed()} 을(를) 사용하세요."
                invalid.append((rule.key, m["value"], msg))

    hints = list(dict.fromkeys(msg for _, _, msg in invalid))
    return CodeValidationResult(ok=not invalid, invalid_literals=invalid, hints=hints)


def code_values_prompt_lines(max_rules: int = 8) -> list[str]:
    rules = sorted(get_code_registry().rules.values(), key=lambda r: r.key)
    lines = []
    for rule in rules[:max_rules]:
        line = f"{rule.key} ({rule.label}): {rule.format_allowed()}"
        if rule.forbidden_literals:
            line += f" (금지: {', '.join(sorted(rule.forbidden_literals)[:6])})"
        lines.append(line)
    if len(rules) > max_rules:
        lines.append(f"외 {len(rules) - max_rules}개 컬럼")
    return lines


def save_code_values(column_values: dict[str, dict], *, source: str = "mes_api") -> Path:
    payload = {
        "_comment": "scripts/collect_code_values.py 로 갱신",
        "collected_at": datetime.now(UTC).isoformat(),
        "source": source,
        "columns": column_values,
    }
    CODE_VALUES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    get_code_registry.cache_clear()
    return CODE_VALUES_PATH


def load_profile_columns() -> list[dict]:
    return list(json.loads(CODE_PROFILE_PATH.read_text(encoding="utf-8")).get("columns") or [])
