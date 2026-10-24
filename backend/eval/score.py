"""
벤치마크 결과 집계 (VS, EX, Table F1)

실행 방법:
  python eval/score.py eval/results/run_FULL_20260602.csv
  python eval/score.py eval/results/run_FULL_20260602.csv --by difficulty
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


def normalize_sql(sql: str) -> str:
    if not sql:
        return ""
    s = sql.strip().rstrip(";")
    s = re.sub(r"\s+", " ", s, flags=re.MULTILINE)
    return s.lower()


def extract_tables(sql: str) -> set[str]:
    if not sql:
        return set()
    found = set(re.findall(r"\b(CIM_[A-Z0-9_]+)\b", sql, flags=re.IGNORECASE))
    return {t.upper() for t in found}


def table_f1(pred_tables: set[str], gold_tables: set[str]) -> tuple[float, float, float]:
    if not gold_tables:
        return 1.0, 1.0, 1.0
    tp = len(pred_tables & gold_tables)
    prec = tp / len(pred_tables) if pred_tables else 0.0
    rec = tp / len(gold_tables)
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def load_gold(path: Path) -> dict[str, dict]:
    gold = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        gold[row["id"]] = row
    return gold


def score_row(row: dict, gold: dict) -> dict:
    qid = row.get("id", "")
    g = gold.get(qid, {})
    gold_tables = {t.upper() for t in g.get("tables", [])}
    pred_sql = row.get("pred_sql", "") or ""
    gold_sql = g.get("gold_sql", "") or row.get("gold_sql", "")

    valid_sql = str(row.get("valid_sql", "")).lower() in ("true", "1", "yes")
    if not valid_sql:
        valid_sql = bool(pred_sql) and pred_sql.strip().upper().startswith("SELECT")
        valid_sql = valid_sql and "drop " not in pred_sql.lower()

    exec_ok = str(row.get("exec_ok", "")).lower() in ("true", "1", "yes")
    gold_exec_ok = str(row.get("gold_exec_ok", "")).lower() in ("true", "1", "yes")

    sql_match = normalize_sql(pred_sql) == normalize_sql(gold_sql)
    pred_tables = extract_tables(pred_sql)
    p, r, f1 = table_f1(pred_tables, gold_tables)

    ex_strict = exec_ok and gold_exec_ok and sql_match
    ex_exec = exec_ok and gold_exec_ok
    ex_loose = exec_ok

    return {
        "id": qid,
        "difficulty": g.get("difficulty", row.get("difficulty", "")),
        "requires_join": g.get("requires_join", ""),
        "valid_sql": valid_sql,
        "exec_ok": exec_ok,
        "gold_exec_ok": gold_exec_ok,
        "sql_match": sql_match,
        "ex_strict": ex_strict,
        "ex_exec": ex_exec,
        "ex_loose": ex_loose,
        "table_precision": round(p, 4),
        "table_recall": round(r, 4),
        "table_f1": round(f1, 4),
    }


def aggregate(scored: list[dict]) -> dict:
    n = len(scored) or 1

    def rate(key: str) -> float:
        return round(100.0 * sum(1 for s in scored if s.get(key)) / n, 2)

    return {
        "n": len(scored),
        "VS_pct": rate("valid_sql"),
        "EX_loose_pct": rate("ex_loose"),
        "EX_exec_pct": rate("ex_exec"),
        "EX_strict_pct": rate("ex_strict"),
        "SQL_match_pct": rate("sql_match"),
        "Table_F1_avg": round(sum(s["table_f1"] for s in scored) / n, 4),
    }


def group_aggregate(scored: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list] = defaultdict(list)
    for s in scored:
        groups[str(s.get(key, ""))].append(s)
    return {k: aggregate(v) for k, v in sorted(groups.items())}


def resolve_results_path(target: Path) -> Path:
    """CSV 경로 해석 (파일, experiment 폴더, glob 패턴, latest.csv)"""
    root = Path(__file__).resolve().parents[1]
    results_dir = Path(__file__).resolve().parent / "results"

    candidates: list[Path] = []
    if not target.is_absolute():
        candidates.append(root / target)
        candidates.append(results_dir / target.name)
    candidates.append(target)

    for p in candidates:
        if p.is_file():
            return p
        if p.is_dir():
            full = sorted(p.glob("run_FULL_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
            if full:
                return full[0]
            any_csv = sorted(p.glob("run_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
            if any_csv:
                return any_csv[0]

    # glob 패턴 (run_FULL_*.csv 등)
    for p in candidates:
        parent = p.parent if p.parent.exists() else results_dir
        pattern = p.name
        matched = sorted(parent.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        if matched:
            return matched[0]

    latest = results_dir / "latest.csv"
    if latest.is_file():
        return latest

    hint = "\n  ".join(
        str(x.relative_to(root)) if x.is_relative_to(root) else str(x)
        for x in sorted(results_dir.glob("**/*.csv"))[:12]
    )
    raise FileNotFoundError(
        f"결과 CSV를 찾을 수 없습니다: {target}\n"
        f"eval/results 아래 예시:\n  {hint}\n"
        f"예: python eval/score.py eval/results/experiment_*/run_FULL_*.csv --by difficulty"
    )


def main():
    parser = argparse.ArgumentParser(description="Score benchmark CSV")
    parser.add_argument(
        "results_csv",
        type=Path,
        nargs="?",
        default=Path("eval/results/latest.csv"),
        help="CSV 파일, experiment 폴더, 또는 glob (기본: eval/results/latest.csv)",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("data/benchmark/mes_nl2sql_gold_v3.jsonl"),
    )
    parser.add_argument("--by", choices=["difficulty", "requires_join"], default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    gold_path = args.gold if args.gold.is_absolute() else root / args.gold
    csv_path = resolve_results_path(args.results_csv)

    gold = load_gold(gold_path)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    scored = [score_row(r, gold) for r in rows]
    summary = aggregate(scored)

    print(f"\n=== Summary: {csv_path} ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if args.by:
        print(f"\n=== By {args.by} ===")
        for group, stats in group_aggregate(scored, args.by).items():
            print(f"  [{group or '(empty)'}] EX_exec={stats['EX_exec_pct']}%  VS={stats['VS_pct']}%  n={stats['n']}")


if __name__ == "__main__":
    main()
