"""
실행 방법: python eval/test_known_errors.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.validation.sql_validator import validate_sql  # noqa: E402

CSV = ROOT / "eval/known_errors.csv"
SCHEMA = ROOT / "data/mes_schema.json"

MANUAL_SAMPLES = [
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
        "label": "NODENAME 환각 (실제 pred와 동일 qualified)",
        "sql": "SELECT CIM_PROCESSNODE.NODENAME FROM CIM_PROCESSDEFINITION JOIN CIM_PROCESSNODE WITH (NOLOCK) ON 1=1",
        "expect_block": True,
        "category": "invalid_column",
    },
    {
        "id": "Q005-bad",
        "label": "ORDERID 환각 (실제 pred)",
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
        "label": "자재LOT→CIM_LOT 혼동",
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
        "label": "공정 구역→잘못된 테이블",
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


def load_schema_cols():
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return {
        t["name"].upper(): {c["name"].upper() for c in t["columns"]}
        for t in data["tables"]
    }


def classify_remaining(sql: str, table_cols: dict) -> list[str]:
    issues = []
    if re.search(r"\bISHOLD\s*=\s*'TRUE'", sql, re.I):
        issues.append("code: ISHOLD=TRUE")
    for t in re.findall(r"\b(CIM_[A-Z][A-Z0-9_]*)\b", sql, re.I):
        if t.upper() not in table_cols:
            issues.append(f"table: {t}")
    for t, c in re.findall(
        r"\b(CIM_[A-Z][A-Z0-9_]*)\s*\.\s*([A-Z][A-Z0-9_]*)\b", sql, re.I
    ):
        t, c = t.upper(), c.upper()
        if t in table_cols and c not in table_cols[t]:
            issues.append(f"column: {t}.{c}")
    if " WITH (NOLOCK)" not in sql.upper() and "CIM_" in sql.upper():
        issues.append("hint: NOLOCK 누락 가능")
    return issues


def main():
    table_cols = load_schema_cols()
    results = []

    if CSV.exists():
        for row in csv.DictReader(CSV.open(encoding="utf-8-sig")):
            if row.get("exec_ok", "").lower() != "false":
                continue
            pred = (row.get("pred_sql") or "").strip()
            if not pred:
                continue
            vr = validate_sql(pred, question=row["question"])
            results.append(
                {
                    "id": row["id"],
                    "source": "csv_fail",
                    "question": row["question"][:40],
                    "blocked": not vr.ok,
                    "error": vr.error_message()[:200],
                    "expect_block": None,
                    "remaining": classify_remaining(pred, table_cols)
                    if vr.ok
                    else [],
                }
            )

    for s in MANUAL_SAMPLES:
        vr = validate_sql(s["sql"], question=s.get("question"))
        ok_block = not vr.ok
        match = ok_block == s["expect_block"]
        results.append(
            {
                "id": s["id"],
                "source": "manual",
                "label": s["label"],
                "category": s["category"],
                "blocked": ok_block,
                "error": vr.error_message()[:200],
                "expect_block": s["expect_block"],
                "match": match,
                "remaining": classify_remaining(s["sql"], table_cols) if vr.ok else [],
            }
        )

    print("=" * 72)
    print("1) 수동 샘플 (기대: bad=차단, good=통과)")
    print("=" * 72)
    for r in results:
        if r["source"] != "manual":
            continue
        status = "OK" if r.get("match") else "MISMATCH"
        act = "차단" if r["blocked"] else "통과"
        exp = "차단" if r["expect_block"] else "통과"
        print(f"[{status}] {r['id']:12} expect={exp} actual={act} ({r['category']})")
        if r["blocked"] and r["error"]:
            print(f"         -> {r['error'][:100]}")
        if r.get("remaining"):
            print(f"         !! 검증 통과했지만: {', '.join(r['remaining'])}")

    print()
    print("=" * 72)
    print("2) 과거 FULL 실패 20건 pred_sql - 검증기 차단 여부")
    print("=" * 72)
    csv_rows = [r for r in results if r["source"] == "csv_fail"]
    blocked_n = sum(1 for r in csv_rows if r["blocked"])
    print(f"차단: {blocked_n}/{len(csv_rows)}  |  통과(여전히 DB위험): {len(csv_rows)-blocked_n}")
    print()
    for r in csv_rows:
        flag = "BLOCK" if r["blocked"] else "PASS "
        extra = ""
        if not r["blocked"] and r["remaining"]:
            extra = " | " + ", ".join(r["remaining"][:3])
        elif r["blocked"]:
            extra = " | " + (r["error"][:70] if r["error"] else "")
        print(f"  {flag} {r['id']} {r['question']}{extra}")

    print()
    print("=" * 72)
    print("3) 아직 검증기로 막기 어려운 유형 (통과한 실패 샘플)")
    print("=" * 72)
    still = [r for r in csv_rows if not r["blocked"]]
    cats = {}
    for r in still:
        rem = r["remaining"] or ["semantic/join/wrong-table"]
        key = rem[0].split(":")[0] if rem else "semantic"
        cats[key] = cats.get(key, 0) + 1
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  - {k}: {v}건")
    if still:
        print("\n  대표 ID:", ", ".join(r["id"] for r in still[:12]))


if __name__ == "__main__":
    main()
