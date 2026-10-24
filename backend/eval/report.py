"""
ablation 결과 비교표 생성

실행 방법:
  python eval/report.py eval/results/experiment_20260602_120000
  python eval/report.py eval/results/run_FULL_*.csv --gold data/benchmark/mes_nl2sql_gold_v3.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.score import aggregate, load_gold, score_row  # noqa: E402

PRESET_ORDER = ["B0", "B1", "B2", "B3", "FULL"]


def score_csv(csv_path: Path, gold_path: Path) -> dict:
    gold = load_gold(gold_path)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    scored = [score_row(r, gold) for r in rows]
    summary = aggregate(scored)
    preset = rows[0].get("preset", "") if rows else csv_path.stem.split("_")[1]
    summary["preset"] = preset
    summary["csv"] = csv_path.name
    return summary


def find_csvs(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() == ".csv":
        return [target]
    if target.is_dir():
        manifest = target / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return [target / p for p in data.get("csv_files", [])]
        return sorted(target.glob("run_*.csv"))
    return sorted(target.parent.glob(target.name))


def build_markdown(summaries: list[dict], out_dir: Path) -> str:
    lines = [
        "# NL→SQL Ablation 결과",
        "",
        "| Preset | n | VS (%) | EX_exec (%) | EX_strict (%) | Table F1 |",
        "|--------|---|--------|-------------|---------------|----------|",
    ]
    by_preset = {s.get("preset", "").upper(): s for s in summaries}
    for p in PRESET_ORDER:
        s = by_preset.get(p)
        if not s:
            continue
        lines.append(
            f"| {p} | {s['n']} | {s['VS_pct']} | {s['EX_exec_pct']} | "
            f"{s['EX_strict_pct']} | {s['Table_F1_avg']} |"
        )
    lines.extend(["", "## 해석 가이드", "", "- **VS**: 유효 SELECT 생성 비율", "- **EX_exec**: 골드·예측 SQL 모두 DB 실행 성공", "- **EX_strict**: 실행 성공 + SQL 문자열 일치", ""])
    md = "\n".join(lines)
    (out_dir / "paper_table.md").write_text(md, encoding="utf-8")
    return md


def main():
    parser = argparse.ArgumentParser(description="Build ablation comparison report")
    parser.add_argument("target", type=Path, help="CSV file, glob dir, or experiment folder")
    parser.add_argument("--gold", type=Path, default=Path("data/benchmark/mes_nl2sql_gold_v3.jsonl"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    gold_path = args.gold if args.gold.is_absolute() else ROOT / args.gold
    target = args.target if args.target.is_absolute() else ROOT / args.target
    csvs = find_csvs(target)
    if not csvs:
        print(f"No CSV found under {target}", file=sys.stderr)
        sys.exit(1)

    summaries = [score_csv(p, gold_path) for p in csvs]
    out_dir = args.out or (target if target.is_dir() else target.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_json = out_dir / "ablation_summary.json"
    summary_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_out = out_dir / "ablation_summary.csv"
    if summaries:
        keys = ["preset", "n", "VS_pct", "EX_loose_pct", "EX_exec_pct", "EX_strict_pct", "SQL_match_pct", "Table_F1_avg", "csv"]
        with csv_out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(summaries)

    md = build_markdown(summaries, out_dir)
    print(md)
    print(f"\n[report] → {out_dir / 'paper_table.md'}")
    print(f"[report] → {summary_json}")
    print(f"[report] → {csv_out}")


if __name__ == "__main__":
    main()
