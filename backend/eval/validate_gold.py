"""
eval/validate_gold.py — 골드 SQL DB 실행 검증

Usage (mes-llm-api 루트):
  python eval/validate_gold.py
  python eval/validate_gold.py --gold data/benchmark/mes_nl2sql_gold_v2.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_benchmark import DEFAULT_GOLD, RESULTS_DIR, load_jsonl, run_sql  # noqa: E402


async def validate_all(gold_path: Path, limit: int) -> dict:
    items = load_jsonl(gold_path)
    results = []
    ok_count = 0

    for i, item in enumerate(items, 1):
        qid = item["id"]
        sql = item.get("gold_sql", "")
        print(f"  [{i}/{len(items)}] {qid} ...", end=" ")
        if not sql:
            results.append({"id": qid, "ok": False, "error": "gold_sql empty"})
            print("FAIL (empty)")
            continue
        ok, err, cnt = await run_sql(sql, limit)
        results.append({
            "id": qid,
            "ok": ok,
            "row_count": cnt,
            "error": err,
            "question": item.get("question", ""),
        })
        if ok:
            ok_count += 1
            print(f"OK (rows={cnt})")
        else:
            print(f"FAIL: {err[:80]}")

    return {
        "gold_file": str(gold_path),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total": len(items),
        "passed": ok_count,
        "failed": len(items) - ok_count,
        "pass_rate_pct": round(100.0 * ok_count / len(items), 2) if items else 0,
        "results": results,
        "failed_ids": [r["id"] for r in results if not r["ok"]],
    }


def main():
    parser = argparse.ArgumentParser(description="Validate gold SQL against MES API")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    gold_path = args.gold if args.gold.is_absolute() else ROOT / args.gold
    print(f"[validate_gold] {gold_path} ({len(load_jsonl(gold_path))} items)")
    report = asyncio.run(validate_all(gold_path, args.limit))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or RESULTS_DIR / f"gold_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[validate_gold] {report['passed']}/{report['total']} passed ({report['pass_rate_pct']}%)")
    print(f"  report → {out}")
    if report["failed_ids"]:
        print(f"  failed: {', '.join(report['failed_ids'])}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
