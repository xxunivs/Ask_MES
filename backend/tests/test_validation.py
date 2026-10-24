import csv
import json
from pathlib import Path

import pytest

from app.validation.sql_validator import validate_sql

DATA = Path(__file__).parent / "data"
GOLD = Path(__file__).resolve().parents[1] / "data/benchmark/mes_nl2sql_gold_v3.jsonl"

SAMPLES = [
    {
        "id": "Q002-bad",
        "label": "ISHOLD=TRUE (코드값)",
        "sql": "SELECT LOTID FROM CIM_LOT WITH (NOLOCK) WHERE ISHOLD = 'TRUE'",
        "expect_block": True,
        "category": "code_value",
    },
    {
        "id": "Q002-good",
        "label": "ISHOLD=Y (정답)",
        "sql": "SELECT TOP 100 LOTID FROM CIM_LOT WITH (NOLOCK) WHERE ISHOLD = 'Y'",
        "expect_block": False,
        "category": "code_value",
    },
    {
        "id": "Q008-bad",
        "label": "CIM_MATERIAL 환각",
        "sql": "SELECT STOCKID FROM CIM_MATERIAL WITH (NOLOCK) WHERE SAFETYSTOCK > 0",
        "expect_block": True,
        "category": "invalid_table",
    },
    {
        "id": "Q008-good",
        "label": "CIM_MATERIALDEFINITION 안전재고",
        "sql": "SELECT MATERIALDEFINITIONID, SAFETY_QTY FROM CIM_MATERIALDEFINITION WITH (NOLOCK) WHERE SAFETY_QTY > 0",
        "expect_block": False,
        "category": "invalid_table",
    },
    {
        "id": "Q018-bad",
        "label": "NODENAME 환각",
        "sql": "SELECT CIM_PROCESSNODE.NODENAME FROM CIM_PROCESSDEFINITION JOIN CIM_PROCESSNODE WITH (NOLOCK) ON 1=1",
        "expect_block": True,
        "category": "invalid_column",
    },
    {
        "id": "Q005-bad",
        "label": "ORDERID 환각",
        "sql": "SELECT CIM_PRODUCTORDER.ORDERID FROM CIM_PRODUCTORDER WITH (NOLOCK) JOIN CIM_LOT WITH (NOLOCK) ON CIM_PRODUCTORDER.PRODUCTORDERID = CIM_LOT.PRODUCTORDERID",
        "expect_block": True,
        "category": "invalid_column",
    },
    {
        "id": "Q042-bad",
        "label": "CIM_EQUIPMENTSTATE 환각",
        "sql": "SELECT STATE, COUNT(*) FROM CIM_EQUIPMENTSTATE WITH (NOLOCK) GROUP BY STATE",
        "expect_block": True,
        "category": "invalid_table",
    },
    {
        "id": "Q007-bad",
        "label": "자재 LOT을 CIM_LOT으로 혼동",
        "sql": "SELECT LOTNAME, QTY FROM CIM_LOT WITH (NOLOCK) WHERE QTY = 0",
        "expect_block": True,
        "category": "table_confusion",
        "question": "자재 LOT 중 현재 수량이 0인 것 보여줘",
    },
    {
        "id": "Q007-good",
        "label": "자재 LOT 정답",
        "sql": "SELECT MATERIALLOTID, QTY FROM CIM_MATERIALLOT WITH (NOLOCK) WHERE QTY = 0",
        "expect_block": False,
        "category": "table_confusion",
        "question": "자재 LOT 중 현재 수량이 0인 것 보여줘",
    },
    {
        "id": "Q050-bad",
        "label": "ISHOLD=1 (숫자)",
        "sql": "SELECT TOP 10 LOTID FROM CIM_LOT WITH (NOLOCK) WHERE CIM_LOT.ISHOLD = 1",
        "expect_block": True,
        "category": "code_value",
        "question": "홀드 상태 LOT 중 불량 수량 상위 10건",
    },
    {
        "id": "Q033-bad",
        "label": "공정 구역에 잘못된 테이블",
        "sql": "SELECT DISTINCT CIM_PROCESSSEGMENT.DESCRIPTION FROM CIM_EQUIPMENT WITH (NOLOCK) JOIN CIM_LOT WITH (NOLOCK) ON 1=1 JOIN CIM_PROCESSSEGMENT WITH (NOLOCK) ON 1=1",
        "expect_block": True,
        "category": "table_confusion",
        "question": "공정 구역 전체 목록을 보여줘",
    },
    {
        "id": "Q033-good",
        "label": "공정 구역 정답",
        "sql": "SELECT FACILITYID, FACILITYNAME FROM CIM_FACILITY WITH (NOLOCK)",
        "expect_block": False,
        "category": "table_confusion",
        "question": "공정 구역 전체 목록을 보여줘",
    },
]


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["id"] for s in SAMPLES])
def test_manual_samples(sample):
    blocked = not validate_sql(sample["sql"], question=sample.get("question")).ok
    assert blocked == sample["expect_block"], sample["label"]


# 실제 DB 실행에서 실패했던 생성 SQL 20건
def test_known_errors_blocked_before_db():
    rows = list(csv.DictReader((DATA / "known_errors.csv").open(encoding="utf-8-sig")))
    blocked = sum(not validate_sql(r["pred_sql"], question=r["question"]).ok for r in rows)
    assert len(rows) == 20 and blocked >= 19


def test_gold_sql_passes():
    gold = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = [g["id"] for g in gold if not validate_sql(g["gold_sql"], question=g["question"]).ok]
    assert failed == []


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT TOP 10 L.LOTID, L.NOPE FROM CIM_LOT L WITH (NOLOCK)", "CIM_LOT.NOPE"),
        ("SELECT TOP 10 PROCESSSEGMENTNAME FROM CIM_LOTDEFECT WITH (NOLOCK)", "CIM_LOTDEFECT.PROCESSSEGMENTNAME"),
        ("SELECT TOP 10 P.PRODUCTTYPE FROM CIM_LOT L WITH (NOLOCK)", "alias: P"),
    ],
)
def test_unknown_columns_and_aliases(sql, expected):
    result = validate_sql(sql)
    assert not result.ok and expected in result.error_message()


def test_bracket_alias_is_not_a_column():
    sql = "SELECT TOP 10 MATERIALLOTID AS [자재 LOT ID] FROM CIM_MATERIALLOT WITH (NOLOCK) WHERE QTY = 0"
    assert validate_sql(sql).ok


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT TOP 10 E.EQUIPMENTNAME, AVG(L.QTY) AS q FROM CIM_LOT L WITH (NOLOCK), CIM_EQUIPMENT E WITH (NOLOCK) "
        "WHERE L.EQUIPMENTID = E.EQUIPMENTID GROUP BY E.EQUIPMENTNAME",
        "SELECT BATCHTYPE, COUNT(*) AS n FROM CIM_BATCH WITH (NOLOCK) GROUP BY BATCHTYPE "
        "ORDER BY BATCHTYPE OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY",
    ],
)
def test_valid_sql_not_flagged(sql):
    assert validate_sql(sql).ok
