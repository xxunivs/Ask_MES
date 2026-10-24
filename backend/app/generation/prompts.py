from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.generation.date_policy import date_rules
from app.schema import tables_by_name
from app.validation.code_values import code_values_prompt_lines
from app.validation.concept_alignment import alignment_prompt_rules
from app.validation.sql_validator import FORBIDDEN_COLUMNS


@dataclass
class PreviousAttempt:
    sql: str
    error: str
    stage: Literal["validation", "db"]


def _rule_sections() -> list[tuple[str, list[str]]]:
    renamed = [f"{wrong} 대신 {right}" for wrong, right in FORBIDDEN_COLUMNS.items()]
    return [
        (
            "기본",
            [
                "SELECT 문만 작성 (INSERT, UPDATE, DELETE, DROP, EXEC 금지)",
                "모든 테이블에 WITH (NOLOCK)",
                f"스키마에 있는 테이블, 컬럼만 사용. 테이블 목록: {', '.join(sorted(tables_by_name()))}",
                "없는 이름: CIM_MATERIAL 대신 CIM_MATERIALLOT(자재 LOT) 또는 CIM_MATERIALDEFINITION(자재 정의, 안전재고), "
                + ", ".join(renamed),
                "자재 LOT 이름은 MATERIALLOTNAME (LOTNAME 은 CIM_LOT 전용), CIM_BATCH 에는 LOTID 없음 (CIM_LOTBATCHREL 사용)",
                "SELECT * 금지, 필요한 컬럼만 명시",
                "목록 조회는 반드시 SELECT TOP 1000 으로 행 수 제한 (예: SELECT TOP 1000 LOTID FROM CIM_LOT WITH (NOLOCK)). "
                "제한 없는 조회는 차단됨. COUNT, SUM 같은 집계만 하는 질의는 제외",
                "테이블 하나로 답할 수 있는 질문은 JOIN 하지 않기",
            ],
        ),
        ("날짜", date_rules()),
        (
            "집계, 추이",
            [
                "'A별 B' 집계는 A 컬럼으로만 GROUP BY, 질문에 없는 LOTID 같은 컬럼은 SELECT, GROUP BY 에 넣지 않기",
                "일별 추이는 CONVERT(date, 날짜컬럼)",
                "월별 추이는 CONVERT(char(7), 날짜컬럼, 120) 으로 월 단위로 묶고, 기간이 없으면 최근 12개월",
                "'A별 추이'처럼 항목이 함께 나오면 날짜와 A 컬럼을 SELECT, GROUP BY 에 모두 넣기",
                "설비 가동 횟수 추이는 CIM_LOT 의 TRACKINTIME, EQUIPMENTID 로 COUNT(*) "
                "(CIM_EQUIPMENT.RUNCOUNT 는 누적값이라 추이에 쓰지 않음)",
                "불량률은 SUM(LOSSQTY) / NULLIF(SUM(ORIGINALQTY), 0) * 100",
            ],
        ),
        (
            "코드값 (WHERE 절 값)",
            [
                "Y/N 컬럼은 TRUE, FALSE, 1, 0 대신 아래 값만 사용",
                *code_values_prompt_lines(),
            ],
        ),
        ("질문별 테이블", alignment_prompt_rules()),
        (
            "작성 형식",
            [
                "SELECT DISTINCT 금지, TOP 1000 또는 GROUP BY 사용",
                "테이블 alias 는 WITH (NOLOCK) 앞: FROM CIM_LOT L WITH (NOLOCK)",
                "테이블을 괄호로 감싸지 않기",
                "컬럼 alias 에 작은따옴표, 공백, 예약어(DATE, TIME, NAME, VALUE, COUNT, STATE, TYPE, DATA, KEY, INDEX, ORDER) "
                "쓰지 않기: AS 작업일자, AS LOT건수",
            ],
        ),
    ]


def _rules_text() -> str:
    lines, n = [], 0
    for title, rules in _rule_sections():
        lines.append(f"### {title}")
        for rule in rules:
            n += 1
            lines.append(f"{n}. {rule}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _previous_text(prev: PreviousAttempt) -> str:
    if prev.stage == "validation":
        guide = "검증에서 걸렸습니다. 오류를 고쳐 다시 작성하세요."
    else:
        guide = "DB 실행에서 오류가 났습니다. 불필요한 JOIN 과 복잡한 서브쿼리를 줄여 단순하게 다시 작성하세요."
    return f"## 이전 시도\n이전 SQL 이 {guide}\nSQL: {prev.sql}\n오류: {prev.error[:500]}\n\n"


def build_prompt(question: str, schema_ctx: str, db_ctx: str, previous: PreviousAttempt | None = None) -> str:
    return (
        "MES 질문을 MS SQL Server SELECT 문으로 바꾸세요.\n\n"
        f"## 스키마\n{schema_ctx}\n\n"
        f"## 실제 DB 값\n{db_ctx or '(없음)'}\n\n"
        f"## 규칙\n{_rules_text()}\n\n" + (_previous_text(previous) if previous else "") + f"## 질문\n{question}\n\n"
        '설명, 마크다운 없이 {"sql": "SELECT ..."} 형식의 한 줄 JSON만 응답:'
    )


def parse_llm_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start() :])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    # JSON 없을 때 SELECT 문만 추출 (원문 실행 방지)
    sql_match = re.search(r"(SELECT\s.+?)(?:;|$)", raw, re.DOTALL | re.IGNORECASE)
    return {"sql": sql_match.group(1).strip() if sql_match else ""}
