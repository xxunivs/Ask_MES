"""
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
        "# 구성별 결과 (ablation)",
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
            f"| {p} | {s['n']} | {s['VS_pct']} | {s['EX_exec_pct']} | {s['EX_strict_pct']} | {s['Table_F1_avg']} |"
        )
    lines.extend(
        [
            "",
            "1. VS: 유효한 SELECT 문 비율",
            "2. EX_exec: 정답 SQL 과 생성 SQL 이 모두 오류 없이 실행된 비율",
            "3. EX_strict: 실행 성공이면서 정답 SQL 과 문자열까지 같은 비율",
            "",
        ]
    )
    md = "\n".join(lines)
    (out_dir / "paper_table.md").write_text(md, encoding="utf-8")
    return md


def main():
    parser = argparse.ArgumentParser(description="구성별 결과 표 만들기")
    parser.add_argument("target", type=Path, help="결과 CSV 또는 실험 폴더")
    parser.add_argument("--gold", type=Path, default=Path("data/benchmark/mes_nl2sql_gold_v3.jsonl"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    gold_path = args.gold if args.gold.is_absolute() else ROOT / args.gold
    target = args.target if args.target.is_absolute() else ROOT / args.target
    csvs = find_csvs(target)
    if not csvs:
        print(f"결과 CSV 없음: {target}", file=sys.stderr)
        sys.exit(1)

    summaries = [score_csv(p, gold_path) for p in csvs]
    out_dir = args.out or (target if target.is_dir() else target.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_json = out_dir / "ablation_summary.json"
    summary_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_out = out_dir / "ablation_summary.csv"
    if summaries:
        keys = [
            "preset",
            "n",
            "VS_pct",
            "EX_loose_pct",
            "EX_exec_pct",
            "EX_strict_pct",
            "SQL_match_pct",
            "Table_F1_avg",
            "csv",
        ]
        with csv_out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(summaries)

    md = build_markdown(summaries, out_dir)
    print(md)
    print(f"\n결과: {out_dir / 'paper_table.md'}, {summary_json.name}, {csv_out.name}")


if __name__ == "__main__":
    main()
