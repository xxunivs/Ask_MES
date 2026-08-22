"""
eval/run_benchmark.py — NL→SQL 벤치마크 일괄 실행

Usage (mes-llm-api 루트에서):
  python eval/run_benchmark.py --preset FULL --dry-run
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

from app.core.retriever import RetrievalConfig, init_chroma, retrieve_context  # noqa: E402
from app.core.llm import llm_generate  # noqa: E402
from app.core.sql_executor import execute_sql  # noqa: E402
from app.core.live_sample import build_db_context  # noqa: E402
from app.routers.chat import (  # noqa: E402
    NL_TO_SQL_PROMPT,
    _parse_llm_json,
    SCHEMA_RETRY_MAX,
    DB_RETRY_MAX,
)
from app.core.sql_validator import (  # noqa: E402
    validate_sql,
    build_schema_correction_prompt,
    build_db_correction_prompt,
    allowed_tables_hint,
)
from app.core.code_values import code_values_prompt_hint  # noqa: E402
from app.core.concept_alignment import alignment_prompt_rules  # noqa: E402
from app.core.date_policy import date_rules_for_prompt  # noqa: E402

DEFAULT_GOLD = ROOT / "data" / "benchmark" / "mes_nl2sql_gold_v2.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_jsonl(path: Path) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


async def run_sql(sql: str, limit: int) -> tuple[bool, str, int]:
    try:
        res = await execute_sql(sql, limit=limit)
        count = int(res.get("count", 0) or 0)
        return True, "", count
    except Exception as e:
        return False, str(e), 0


async def generate_sql(
    question: str, preset: str, top_k: int | None
) -> tuple[str, str, str, bool, str]:
    """Returns sql, description, schema_ctx_snippet, schema_valid, schema_error."""
    cfg = RetrievalConfig.from_preset(preset)
    schema_ctx = retrieve_context(question, n=top_k, config=cfg)
    try:
        db_ctx = await build_db_context(schema_ctx)
    except Exception as e:
        db_ctx = "(DB 샘플 조회 실패)"
        print(f"[DBContext] 오류: {e}")
    prompt = NL_TO_SQL_PROMPT.format(
        schema=schema_ctx,
        db_context=db_ctx,
        question=question,
        schema_whitelist=allowed_tables_hint(),
        code_values=code_values_prompt_hint() or "(코드값 사전 없음)",
        alignment_rules=alignment_prompt_rules(),
        date_rules=date_rules_for_prompt(),
    )
    sql, desc = "", ""
    schema_valid, schema_error = False, ""

    for attempt in range(SCHEMA_RETRY_MAX + 1):
        raw = await llm_generate(prompt, temperature=0.05, max_tokens=512)
        sql, desc = _parse_llm_json(raw)
        vr = validate_sql(sql or "", question=question)
        schema_valid = vr.ok
        schema_error = vr.error_message()
        if vr.ok:
            break
        if attempt < SCHEMA_RETRY_MAX:
            prompt = build_schema_correction_prompt(
                question, schema_ctx, sql or "", vr
            )

    return sql, desc, schema_ctx, schema_valid, schema_error


async def process_item(
    item: dict,
    preset: str,
    *,
    dry_run: bool,
    execute: bool,
    limit: int,
    top_k: int | None,
) -> dict:
    qid = item["id"]
    question = item["question"]
    gold_sql = item.get("gold_sql", "")

    row = {
        "id": qid,
        "preset": preset,
        "question": question,
        "gold_sql": gold_sql,
        "difficulty": item.get("difficulty", ""),
        "requires_join": item.get("requires_join", ""),
        "pred_sql": "",
        "description": "",
        "valid_sql": False,
        "exec_ok": False,
        "gold_exec_ok": False,
        "pred_row_count": "",
        "gold_row_count": "",
        "db_error": "",
        "gold_db_error": "",
        "llm_error": "",
        "schema_valid": False,
        "schema_error": "",
    }

    if execute and gold_sql:
        ok, err, cnt = await run_sql(gold_sql, limit)
        row["gold_exec_ok"] = ok
        row["gold_row_count"] = cnt
        row["gold_db_error"] = err

    if dry_run:
        return row

    try:
        pred_sql, desc, schema_ctx, schema_ok, schema_err = await generate_sql(
            question, preset, top_k
        )
        row["pred_sql"] = pred_sql
        row["description"] = desc
        row["schema_valid"] = schema_ok
        row["schema_error"] = schema_err
        row["valid_sql"] = (
            bool(pred_sql)
            and pred_sql.strip().upper().startswith("SELECT")
            and schema_ok
        )
    except Exception as e:
        row["llm_error"] = str(e)
        return row

    if execute and row["pred_sql"] and row["schema_valid"]:
        ok, err, cnt = await run_sql(row["pred_sql"], limit)
        for db_attempt in range(DB_RETRY_MAX):
            if ok:
                break
            prompt = build_db_correction_prompt(
                question, schema_ctx, row["pred_sql"], err
            )
            raw = await llm_generate(prompt, temperature=0.05, max_tokens=512)
            retry_sql, retry_desc = _parse_llm_json(raw)
            vr = validate_sql(retry_sql or "", question=question)
            if not vr.ok:
                break
            row["pred_sql"] = retry_sql
            row["description"] = retry_desc or row["description"]
            ok, err, cnt = await run_sql(retry_sql, limit)
        row["exec_ok"] = ok
        row["pred_row_count"] = cnt
        row["db_error"] = err

    return row


async def main_async(args: argparse.Namespace) -> int:
    gold_path = Path(args.gold)
    items = load_jsonl(gold_path)

    if args.ids:
        allow = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if it["id"] in allow]

    if not args.gold_only:
        print("[Benchmark] ChromaDB / 온톨로지 / FK 초기화...")
        init_chroma()

    preset_label = "GOLD" if args.gold_only else args.preset.upper()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"run_{preset_label}_{ts}.csv"

    fieldnames = [
        "id", "preset", "question", "difficulty", "requires_join",
        "gold_sql", "pred_sql", "description",
        "valid_sql", "exec_ok", "gold_exec_ok",
        "pred_row_count", "gold_row_count",
        "db_error", "gold_db_error", "llm_error",
    ]

    rows: list[dict] = []
    for i, item in enumerate(items, 1):
        print(f"  [{i}/{len(items)}] {item['id']} {item['question'][:40]}...")
        if args.gold_only:
            row = {
                "id": item["id"],
                "preset": "GOLD",
                "question": item["question"],
                "gold_sql": item.get("gold_sql", ""),
                "difficulty": item.get("difficulty", ""),
                "requires_join": item.get("requires_join", ""),
                "pred_sql": "",
                "description": "",
                "valid_sql": "",
                "exec_ok": "",
                "gold_exec_ok": False,
                "pred_row_count": "",
                "gold_row_count": "",
                "db_error": "",
                "gold_db_error": "",
                "llm_error": "",
            }
            if args.execute and row["gold_sql"]:
                ok, err, cnt = await run_sql(row["gold_sql"], args.limit)
                row["gold_exec_ok"] = ok
                row["gold_row_count"] = cnt
                row["gold_db_error"] = err
        else:
            row = await process_item(
                item,
                args.preset,
                dry_run=args.dry_run,
                execute=args.execute,
                limit=args.limit,
                top_k=args.top_k,
            )
        rows.append(row)

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    latest = RESULTS_DIR / "latest.csv"
    if latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(out_path.name)
    except OSError:
        import shutil
        shutil.copy(out_path, latest)

    print(f"\n[Benchmark] 완료 → {out_path}")
    if not args.dry_run and not args.gold_only:
        print(f"  점수 집계: python eval/score.py {out_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="MES NL→SQL benchmark runner")
    parser.add_argument(
        "--preset",
        default="FULL",
        choices=["B0", "B1", "B2", "B3", "FULL", "b0", "b1", "b2", "b3", "full"],
        help="RAG ablation preset",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD,
        help="Gold JSONL path",
    )
    parser.add_argument("--ids", default="", help="Comma-separated question ids")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load items only, skip LLM (use with --execute for gold-only)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run SQL via MES API (requires .env MES_API_URL)",
    )
    parser.add_argument(
        "--gold-only",
        action="store_true",
        help="Validate gold SQL execution only (no LLM)",
    )
    parser.add_argument("--limit", type=int, default=100, help="MES API row limit")
    parser.add_argument("--top-k", type=int, default=None, help="RAG top-k override")
    args = parser.parse_args()

    if args.gold_only:
        args.dry_run = False

    exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
