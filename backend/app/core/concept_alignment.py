"""
질의 개념 ↔ SQL 테이블 정합성 검증 (테이블 혼동 방지).

온톨로지/개념 사전으로 식별된 필수 테이블이 SQL에 없으면 DB 실행 전 차단.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import re

from app.core.ontology_loader import get_concept_engine

_CIM_TABLE_RE = re.compile(r"\b(CIM_[A-Z][A-Z0-9_]*)\b", re.IGNORECASE)


def _extract_cim_tables(sql: str) -> set[str]:
    return {m.upper() for m in _CIM_TABLE_RE.findall(sql)}

# (질의에 포함될 문자열들, SQL에 반드시 있어야 할 테이블, 단독 사용 시 오류인 테이블)
_TABLE_ALIGNMENT_RULES: list[tuple[list[str], str, list[str]]] = [
    (["자재 lot", "자재로트", "material lot"], "CIM_MATERIALLOT", ["CIM_LOT"]),
    (["공정 구역", "작업장", "facility"], "CIM_FACILITY", []),
    (["불량 유형", "defect class", "불량유형"], "CIM_DEFECTCLASS", []),
    (["안전재고", "safety stock", "safety qty"], "CIM_MATERIALDEFINITION", ["CIM_MATERIAL"]),
]


@dataclass
class AlignmentResult:
    ok: bool
    hints: list[str] = field(default_factory=list)


def _normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q.lower().strip())


def validate_concept_table_alignment(
    question: str,
    sql: str,
    *,
    engine=None,
) -> AlignmentResult:
    q = _normalize_query(question)
    sql_tables = _extract_cim_tables(sql)
    hints: list[str] = []

    for triggers, required, wrong_solo in _TABLE_ALIGNMENT_RULES:
        if not any(t in q for t in triggers):
            continue
        req = required.upper()
        if req not in sql_tables:
            wrong_present = [w for w in wrong_solo if w.upper() in sql_tables]
            hints.append(
                f"질의 키워드({triggers[0]} 등)에 맞는 테이블 '{req}' 이(가) SQL에 없습니다. "
                f"현재 테이블: {', '.join(sorted(sql_tables)) or '(없음)'}"
                + (
                    f" — '{wrong_present[0]}' 대신 '{req}' 사용"
                    if wrong_present
                    else ""
                )
            )

    # 온톨로지: 단일 테이블만 매칭되고 SQL에 없을 때
    try:
        eng = engine or get_concept_engine()
        expected = eng.find_tables(question)
        if len(expected) == 1 and expected[0].upper() not in sql_tables:
            only = expected[0].upper()
            if not hints:
                hints.append(
                    f"개념 매핑 테이블 '{only}' 이 SQL에 없습니다. "
                    f"현재: {', '.join(sorted(sql_tables)) or '(없음)'}"
                )
    except Exception:
        pass

    seen: set[str] = set()
    unique = [h for h in hints if h not in seen and not seen.add(h)]  # type: ignore
    return AlignmentResult(ok=not unique, hints=unique)


def alignment_prompt_rules() -> str:
    lines = ["질의-테이블 매핑 (필수):"]
    for triggers, required, _ in _TABLE_ALIGNMENT_RULES:
        lines.append(f"- '{triggers[0]}' … → 반드시 {required}")
    return "\n".join(lines)
