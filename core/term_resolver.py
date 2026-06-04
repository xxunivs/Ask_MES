"""
Dynamic MES ambiguous term resolver.

The resolver does not use fixed role-score rules. For every question it asks
the configured LLM to identify ambiguous MES terms and choose SQL meanings from
the current role, view/context, retrieved schema, and live DB context.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from core.ollama import llm_generate

_BASE_DIR = os.path.dirname(__file__)
SCHEMA_PATH = os.path.join(_BASE_DIR, "../data/mes_schema.json")

ROLE_LABELS = {
    "quality": "품질팀",
    "production": "생산팀",
    "equipment": "설비팀",
    "management": "관리팀",
    "general": "일반",
}

VIEW_LABELS = {
    "chat": "채팅",
    "quality": "품질",
    "production": "생산",
    "equipment": "설비",
    "order": "작업지시",
    "lot": "LOT",
    "analysis": "통계",
}

IMPORTANT_COLUMN_HINTS = (
    "QTY",
    "LOSS",
    "DEFECT",
    "RESULT",
    "STATE",
    "TIME",
    "DATE",
    "EQUIPMENT",
    "PRODUCT",
    "PROCESS",
    "ORDER",
    "RUN",
    "TRACK",
)

AMBIGUOUS_TERM_HINTS = (
    "불량",
    "완료",
    "실적",
    "생산",
    "정지",
    "가동",
    "지연",
    "효율",
    "수율",
    "손실",
)

TERM_RESOLUTION_PROMPT = """당신은 MES 자연어 질의를 SQL 의미로 해석하는 전문가입니다.
사용자 질문 안에 모호한 제조 용어가 있으면, 그 용어가 이번 질문에서 어떤 SQL 의미인지 결정하세요.

중요:
- 고정 규칙표처럼 기계적으로 판단하지 마세요.
- 사용자 역할, 현재 화면/공정 맥락, 이전 대화, 검색된 스키마, 실제 DB 탐색 결과를 모두 근거로 삼으세요.
- 같은 단어라도 역할과 공정 맥락에 따라 다른 SQL 의미가 될 수 있습니다.
- SQL 생성에 직접 쓸 수 있는 테이블/컬럼/집계 힌트를 제시하세요.
- 비율/률 계산 SQL 힌트는 반드시 `* 100`을 사용하세요. 임의 숫자를 만들지 마세요.
- 근거가 약하면 confidence를 낮게 주고 alternatives에 다른 후보를 남기세요.

## 사용자 역할
{user_role_label}

## 현재 화면/공정 맥락
{current_view_label}

## 이전 대화 맥락
{conversation_context}

## 사용자 질문
{question}

## 질문에서 우선 검토할 수 있는 모호 제조 용어
{detected_terms}

## 검색된 MES 스키마/온톨로지/JOIN 정보
{schema_context}

## 실제 MES DB 탐색 결과
{db_context}

## 후보 컬럼 인벤토리
{column_inventory}

반드시 아래 JSON 형식으로만 응답하세요. 모호어가 없으면 resolved_terms는 빈 배열입니다.
{{
  "resolved_terms": [
    {{
      "term": "불량",
      "selected_meaning": "불량률",
      "sql_hint": "SUM(CIM_LOT.LOSSQTY) / NULLIF(SUM(CIM_LOT.ORIGINALQTY), 0) * 100",
      "selected_columns": ["CIM_LOT.LOSSQTY", "CIM_LOT.ORIGINALQTY"],
      "confidence": 0.82,
      "evidence": ["품질팀 맥락", "LOSSQTY/ORIGINALQTY 컬럼 존재", "질문이 비율성 지표를 요구"],
      "alternatives": [
        {{"meaning": "불량수량", "sql_hint": "SUM(CIM_LOTDEFECT.DEFECTQTY)", "reason": "생산팀 맥락이면 가능"}}
      ]
    }}
  ]
}}

JSON 응답:"""

_SCHEMA_CACHE: dict[str, dict[str, Any]] | None = None


def _clip(text: str, max_chars: int) -> str:
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... (길이 제한으로 일부 생략)"


def _load_schema() -> dict[str, dict[str, Any]]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    tables: dict[str, dict[str, Any]] = {}
    for table in raw.get("tables", []):
        name = table.get("name", "")
        if not name:
            continue
        tables[name.upper()] = {
            "description": table.get("description", ""),
            "columns": table.get("columns", []),
        }

    _SCHEMA_CACHE = tables
    return tables


def _parse_json_object(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start() :])
            if isinstance(obj, dict):
                if "resolved_terms" not in obj and {"term", "selected_meaning"}.issubset(obj):
                    return {"resolved_terms": [obj]}
                return obj
        except json.JSONDecodeError:
            continue
    return {"resolved_terms": []}


def _schema_tables_from_context(schema_context: str) -> list[str]:
    schema = _load_schema()
    found: list[str] = []
    for table in re.findall(r"\bCIM_[A-Z0-9_]+\b", schema_context.upper()):
        if table in schema and table not in found:
            found.append(table)
    return found[:8]


def _keyword_tokens(question: str, conversation_context: list[str] | None) -> set[str]:
    text = " ".join([question, *(conversation_context or [])]).upper()
    tokens = set(re.findall(r"[A-Z0-9_]{2,}", text))

    ko_hints = {
        "불량": ("DEFECT", "LOSS", "QTY"),
        "완료": ("STATE", "RESULT", "END", "TRACKOUT"),
        "실적": ("RESULT", "QTY", "TRACK"),
        "생산": ("QTY", "PRODUCT", "LOT"),
        "설비": ("EQUIPMENT", "RUN", "STATE"),
        "가동": ("RUN", "TRACK", "EQUIPMENT"),
        "정지": ("STATE", "OPERATION", "EQUIPMENT"),
        "지연": ("DUE", "DELIVERY", "END"),
        "납기": ("DUE", "DELIVERY", "END"),
        "수율": ("QTY", "ORIGINAL", "LOSS"),
        "효율": ("RESULT", "QTY", "RUN"),
        "손실": ("LOSS", "QTY"),
    }
    compact = text.replace(" ", "")
    for ko, hints in ko_hints.items():
        if ko in compact:
            tokens.update(hints)
    return tokens


def _detected_ambiguous_terms(question: str) -> list[str]:
    compact = question.replace(" ", "")
    return [term for term in AMBIGUOUS_TERM_HINTS if term in compact]


def _build_column_inventory(
    question: str,
    schema_context: str,
    conversation_context: list[str] | None,
    max_lines: int = 80,
) -> str:
    schema = _load_schema()
    context_tables = _schema_tables_from_context(schema_context)
    tokens = _keyword_tokens(question, conversation_context)
    lines: list[str] = []

    table_names = context_tables or list(schema.keys())
    for table in table_names:
        info = schema.get(table)
        if not info:
            continue
        selected: list[str] = []
        for col in info.get("columns", []):
            name = str(col.get("name", ""))
            desc = str(col.get("description", ""))
            haystack = f"{name} {desc}".upper()
            if (
                any(token in haystack for token in tokens)
                or any(hint in name.upper() for hint in IMPORTANT_COLUMN_HINTS)
                or table in context_tables
            ):
                selected.append(f"{table}.{name}({desc or col.get('type', '')})")
            if len(selected) >= 14:
                break
        if selected:
            lines.append(f"- {table}: " + ", ".join(selected))
        if len(lines) >= max_lines:
            break

    return "\n".join(lines) if lines else "(후보 컬럼 없음)"


def _column_exists(column_ref: str) -> bool:
    match = re.match(r"^\s*(CIM_[A-Z0-9_]+)\.([A-Z0-9_]+)\s*$", column_ref.upper())
    if not match:
        return False
    table, column = match.groups()
    schema = _load_schema()
    columns = {str(c.get("name", "")).upper() for c in schema.get(table, {}).get("columns", [])}
    return column in columns


def _append_column_validation(resolution: dict[str, Any]) -> dict[str, Any]:
    for item in resolution.get("resolved_terms", []) or []:
        selected_columns = item.get("selected_columns") or []
        if not isinstance(selected_columns, list):
            selected_columns = []
        valid = [col for col in selected_columns if isinstance(col, str) and _column_exists(col)]
        invalid = [col for col in selected_columns if isinstance(col, str) and not _column_exists(col)]
        item["validated_columns"] = valid
        item["invalid_columns"] = invalid

        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        if valid:
            evidence.append("스키마 검증 통과: " + ", ".join(valid[:5]))
        if invalid:
            evidence.append("스키마에서 확인되지 않은 후보: " + ", ".join(invalid[:5]))
        item["evidence"] = evidence[:8]
    return resolution


async def resolve_ambiguous_terms(
    question: str,
    user_role: str = "general",
    current_view: str = "chat",
    conversation_context: list[str] | None = None,
    schema_context: str = "",
    db_context: str = "",
) -> dict[str, Any] | None:
    """Dynamically resolve ambiguous MES terms using LLM + schema/DB evidence."""
    normalized_role = (user_role or "general").lower()
    normalized_view = (current_view or "chat").lower()
    column_inventory = _build_column_inventory(question, schema_context, conversation_context)
    previous_context = "\n".join(f"- {text}" for text in (conversation_context or [])[-4:]) or "(없음)"
    detected_terms = _detected_ambiguous_terms(question)
    detected_terms_text = ", ".join(detected_terms) if detected_terms else "(질문에서 명확한 후보 없음. 그래도 모호어가 있는지 판단)"

    prompt = TERM_RESOLUTION_PROMPT.format(
        user_role_label=ROLE_LABELS.get(normalized_role, normalized_role),
        current_view_label=VIEW_LABELS.get(normalized_view, normalized_view),
        conversation_context=_clip(previous_context, 600),
        question=question,
        detected_terms=detected_terms_text,
        schema_context=_clip(schema_context or "(스키마 컨텍스트 없음)", 2800),
        db_context=_clip(db_context or "(실제 DB 탐색 결과 없음)", 1200),
        column_inventory=_clip(column_inventory, 1800),
    )

    try:
        raw = await llm_generate(prompt, temperature=0.0, max_tokens=420)
        resolution = _parse_json_object(raw)
    except Exception as exc:
        print(f"[TERM_RESOLVER] LLM 해석 실패: {exc}")
        return None

    resolved_terms = resolution.get("resolved_terms")
    if not isinstance(resolved_terms, list) or not resolved_terms:
        return None

    resolution["user_role"] = normalized_role
    resolution["user_role_label"] = ROLE_LABELS.get(normalized_role, normalized_role)
    resolution["current_view"] = normalized_view
    resolution["current_view_label"] = VIEW_LABELS.get(normalized_view, normalized_view)
    resolution["mode"] = "dynamic_llm_schema_db"
    return _append_column_validation(resolution)


def format_term_resolution_for_prompt(resolution: dict[str, Any] | None) -> str:
    if not resolution:
        return "(감지된 모호 제조 용어 없음)"

    lines = [
        f"- 해석 방식: {resolution.get('mode', 'dynamic')}",
        f"- 사용자 역할: {resolution.get('user_role_label', '일반')}",
        f"- 현재 맥락: {resolution.get('current_view_label', '채팅')}",
    ]
    for item in resolution.get("resolved_terms", []):
        term = item.get("term", "")
        meaning = item.get("selected_meaning", "")
        sql_hint = item.get("sql_hint", "")
        confidence = item.get("confidence", "")
        lines.append(f"- '{term}' → '{meaning}'로 해석(confidence={confidence}). SQL 힌트: {sql_hint}")
        columns = item.get("validated_columns") or item.get("selected_columns") or []
        if columns:
            lines.append("  우선 컬럼: " + ", ".join(str(col) for col in columns[:6]))
        evidence = item.get("evidence") or []
        if evidence:
            lines.append("  근거: " + " / ".join(str(reason) for reason in evidence[:5]))
    return "\n".join(lines)


def format_term_resolution_for_user(resolution: dict[str, Any] | None) -> str:
    if not resolution:
        return ""

    parts: list[str] = []
    for item in resolution.get("resolved_terms", []):
        term = item.get("term", "")
        meaning = item.get("selected_meaning", "")
        confidence = item.get("confidence")
        evidence = item.get("evidence") or []
        reason = str(evidence[0]) if evidence else "역할, 맥락, 스키마/DB 상태를 기준으로 판단"
        suffix = f", 신뢰도 {confidence}" if confidence not in (None, "") else ""
        parts.append(f"'{term}'은 {meaning}로 해석했습니다{suffix}. ({reason})")
    return "\n".join(parts)
