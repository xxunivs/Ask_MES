from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.sql_text import extract_cim_tables

# (질문 키워드, 써야 할 테이블, 대신 잘못 쓰는 테이블)
_TABLE_ALIGNMENT_RULES: list[tuple[list[str], list[str], list[str]]] = [
    (["자재 lot", "자재로트", "material lot"], ["CIM_MATERIALLOT", "CIM_LOTMATERIALLOTREL"], ["CIM_LOT"]),
    (["공정 구역", "작업장", "facility"], ["CIM_FACILITY"], []),
    (["불량 유형", "defect class", "불량유형"], ["CIM_DEFECT", "CIM_DEFECTCLASS"], []),
    (["안전재고", "safety stock", "safety qty"], ["CIM_MATERIALDEFINITION"], ["CIM_MATERIAL"]),
]


@dataclass
class AlignmentResult:
    ok: bool
    hints: list[str] = field(default_factory=list)


def _normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q.lower().strip())


def validate_concept_table_alignment(question: str, sql: str) -> AlignmentResult:
    q = _normalize_query(question)
    sql_tables = extract_cim_tables(sql)
    hints: list[str] = []
    for triggers, allowed, wrong in _TABLE_ALIGNMENT_RULES:
        if not any(t in q for t in triggers) or sql_tables & set(allowed):
            continue
        hint = (
            f"'{triggers[0]}' 질문에는 {' 또는 '.join(allowed)} 테이블이 필요합니다. "
            f"현재 테이블: {', '.join(sorted(sql_tables)) or '(없음)'}."
        )
        misused = [w for w in wrong if w in sql_tables]
        if misused:
            hint += f" {misused[0]} 대신 {allowed[0]} 을(를) 사용하세요."
        hints.append(hint)
    return AlignmentResult(ok=not hints, hints=hints)


def alignment_prompt_rules() -> list[str]:
    return [f"'{triggers[0]}' 질문은 {' 또는 '.join(allowed)} 사용" for triggers, allowed, _ in _TABLE_ALIGNMENT_RULES]
