"""
질의 개념 ↔ SQL 테이블 정합성 검증 (테이블 혼동 방지).

명시 규칙의 허용 테이블이 SQL에 하나도 없으면 DB 실행 전 차단.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import re

_CIM_TABLE_RE = re.compile(r"\b(CIM_[A-Z][A-Z0-9_]*)\b", re.IGNORECASE)


def _extract_cim_tables(sql: str) -> set[str]:
    return {m.upper() for m in _CIM_TABLE_RE.findall(sql)}

# (질의에 포함될 문자열들, 허용 테이블(하나 이상 필요), 단독 사용 시 오류인 테이블)
# 온톨로지 매핑은 후보 생성용이라 차단 근거로 쓰지 않음 (정답 SQL 오차단 방지)
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
    sql_tables = _extract_cim_tables(sql)
    hints: list[str] = []

    for triggers, allowed, wrong_solo in _TABLE_ALIGNMENT_RULES:
        if not any(t in q for t in triggers):
            continue
        if not sql_tables & set(allowed):
            wrong_present = [w for w in wrong_solo if w in sql_tables]
            names = " 또는 ".join(allowed)
            hints.append(
                f"질의 키워드({triggers[0]} 등)에 맞는 테이블 '{names}' 이(가) SQL에 없습니다. "
                f"현재 테이블: {', '.join(sorted(sql_tables)) or '(없음)'}"
                + (
                    f" — '{wrong_present[0]}' 대신 '{allowed[0]}' 사용"
                    if wrong_present
                    else ""
                )
            )

    return AlignmentResult(ok=not hints, hints=hints)


def alignment_prompt_rules() -> str:
    lines = ["질의-테이블 매핑 (필수):"]
    for triggers, allowed, _ in _TABLE_ALIGNMENT_RULES:
        lines.append(f"- '{triggers[0]}' … → 반드시 {' 또는 '.join(allowed)}")
    return "\n".join(lines)
