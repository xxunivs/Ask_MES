"""
eval/run_all_ablations.py — B0~FULL 5조건 연속 실험 + 논문용 리포트

Usage (mes-llm-api 루트, Ollama + MES API 필요):
  python eval/run_all_ablations.py --execute
  python eval/run_all_ablations.py --presets B1,FULL --execute
  python eval/run_all_ablations.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
PRESETS_DEFAULT = ["B0", "B1", "B2", "B3", "FULL"]


def run_one(python: str, preset: str, gold: Path, execute: bool, limit: int, out_dir: Path) -> Path:
    cmd = [
        python,
        str(EVAL_DIR / "run_benchmark.py"),
        "--preset", preset,
        "--gold", str(gold),
        "--limit", str(limit),
    ]
    if execute:
        cmd.append("--execute")

    print(f"\n{'='*60}\n[ablation] preset={preset}\n{'='*60}")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=False)
    if proc.returncode != 0:
        raise RuntimeError(f"run_benchmark failed for {preset} (exit {proc.returncode})")

    # 가장 최근 결과 CSV 찾기
    results_dir = EVAL_DIR / "results"
    candidates = sorted(
        results_dir.glob(f"run_{preset.upper()}_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No result CSV for preset {preset}")
    latest = candidates[0]
    dest = out_dir / latest.name
    dest.write_bytes(latest.read_bytes())
    return dest


def main():
    parser = argparse.ArgumentParser(description="Run all ablation presets")
    parser.add_argument(
        "--presets",
        default=",".join(PRESETS_DEFAULT),
        help="Comma-separated: B0,B1,B2,B3,FULL",
    )
    parser.add_argument("--gold", type=Path, default=Path("data/benchmark/mes_nl2sql_gold_v2.jsonl"))
    parser.add_argument("--execute", action="store_true", help="Execute SQL via MES API")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM (not useful for ablation)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.dry_run:
        print("[run_all_ablations] --dry-run: ablation에는 --execute 권장 (LLM 생성 필요)")
        return

    gold = args.gold if args.gold.is_absolute() else ROOT / args.gold
    presets = [p.strip().upper() for p in args.presets.split(",") if p.strip()]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out or (EVAL_DIR / "results" / f"experiment_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_files: list[str] = []
    for preset in presets:
        dest = run_one(args.python, preset, gold, args.execute, args.limit, out_dir)
        csv_files.append(dest.name)

    manifest = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "gold": str(gold),
        "presets": presets,
        "execute": args.execute,
        "csv_files": csv_files,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 리포트 생성
    report_cmd = [
        args.python,
        str(EVAL_DIR / "report.py"),
        str(out_dir),
        "--gold", str(gold),
        "--out", str(out_dir),
    ]
    subprocess.run(report_cmd, cwd=str(ROOT), check=True)

    print(f"\n[run_all_ablations] 완료 → {out_dir}")
    print(f"  논문 표: {out_dir / 'paper_table.md'}")


if __name__ == "__main__":
    main()
