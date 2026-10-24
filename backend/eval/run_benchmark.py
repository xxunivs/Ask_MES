"""
웹 API 와 같은 파이프라인(app/core/pipeline.py)의 질문 세트 일괄 실행 및 CSV 저장

실행 방법 (backend/ 에서):
  python eval/run_benchmark.py --preset FULL --execute
  python eval/run_benchmark.py --preset B1 --execute --ids Q001,Q002
  python eval/run_benchmark.py --gold-only --execute
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.pipeline import run_pipeline  # noqa: E402
from app.core.retriever import init_chroma  # noqa: E402
from app.core.sql_executor import execute_sql  # noqa: E402

DEFAULT_GOLD = ROOT / "data" / "benchmark" / "mes_nl2sql_gold_v3.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
FIELDNAMES = [
    "id", "preset", "question", "difficulty", "requires_join",
    "gold_sql", "pred_sql", "description",
    "valid_sql", "exec_ok", "gold_exec_ok",
    "pred_row_count", "gold_row_count",
    "db_error", "gold_db_error", "llm_error",
]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_sql(sql: str, limit: int) -> tuple[bool, str, int]:
    try:
        res = await execute_sql(sql, limit=limit)
        return True, "", int(res.get("count", 0) or 0)
    except Exception as e:
        return False, str(e), 0


async def process_item(item: dict, preset: str, *, gold_only: bool, execute: bool, limit: int, top_k: int | None) -> dict:
    row = {
        "id": item["id"], "preset": "GOLD" if gold_only else preset, "question": item["question"],
        "difficulty": item.get("difficulty", ""), "requires_join": item.get("requires_join", ""),
        "gold_sql": item.get("gold_sql", ""), "pred_sql": "", "description": "",
        "valid_sql": False, "exec_ok": False, "gold_exec_ok": False,
        "pred_row_count": "", "gold_row_count": "", "db_error": "", "gold_db_error": "", "llm_error": "",
    }

    if execute and row["gold_sql"]:
        row["gold_exec_ok"], row["gold_db_error"], row["gold_row_count"] = await run_sql(row["gold_sql"], limit)
    if gold_only:
        return row

    try:
        result = await run_pipeline(item["question"], preset=preset, top_k=top_k, limit=limit, execute=execute)
    except Exception as e:
        row["llm_error"] = str(e)
        return row

    row["pred_sql"] = result.sql
    row["valid_sql"] = bool(result.sql) and result.sql.upper().startswith("SELECT") and result.schema_valid
    if execute and result.schema_valid:
        row["exec_ok"] = result.executed
        row["pred_row_count"] = result.data["count"] if result.data else 0
        row["db_error"] = result.db_error
    return row


async def main_async(args: argparse.Namespace) -> int:
    items = load_jsonl(Path(args.gold))
    if args.ids:
        allow = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if it["id"] in allow]

    if not args.gold_only:
        print("[Benchmark] ChromaDB / 온톨로지 / FK 초기화...")
        init_chroma()

    preset = args.preset.upper()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"run_{'GOLD' if args.gold_only else preset}_{datetime.now():%Y%m%d_%H%M%S}.csv"

    rows = []
    for i, item in enumerate(items, 1):
        print(f"  [{i}/{len(items)}] {item['id']} {item['question'][:40]}...", flush=True)
        rows.append(await process_item(
            item, preset, gold_only=args.gold_only, execute=args.execute, limit=args.limit, top_k=args.top_k,
        ))

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    latest = RESULTS_DIR / "latest.csv"
    latest.unlink(missing_ok=True)
    latest.symlink_to(out_path.name)

    print(f"\n[Benchmark] 완료 → {out_path}")
    if not args.gold_only:
        print(f"  점수 집계: python eval/score.py {out_path} --gold {args.gold}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="MES NL→SQL benchmark runner")
    parser.add_argument("--preset", default="FULL", type=str.upper, choices=["B0", "B1", "B2", "B3", "FULL"],
                        help="검색 구성 (ablation)")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="정답 질문 세트 JSONL")
    parser.add_argument("--ids", default="", help="쉼표로 구분한 질문 ID")
    parser.add_argument("--execute", action="store_true", help="생성 SQL 과 정답 SQL 을 DB 에서 실행")
    parser.add_argument("--gold-only", action="store_true", help="정답 SQL 실행만 확인 (LLM 미사용)")
    parser.add_argument("--limit", type=int, default=100, help="결과 행 수 상한")
    parser.add_argument("--top-k", type=int, default=None, help="벡터 검색 top-k")
    exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
