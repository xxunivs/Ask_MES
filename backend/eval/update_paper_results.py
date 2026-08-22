"""
실험 폴더 결과로 논문 초안 수치·표 갱신

Usage:
  python eval/update_paper_results.py eval/results/experiment_YYYYMMDD_HHMMSS
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.report import PRESET_ORDER, build_markdown, find_csvs, score_csv  # noqa: E402

GOLD = ROOT / "data/benchmark/mes_nl2sql_gold_v2.jsonl"


def load_summaries(exp_dir: Path) -> list[dict]:
    csvs = find_csvs(exp_dir)
    return [score_csv(p, GOLD) for p in csvs]


def patch_section_43(summaries: list[dict], exp_dir: Path) -> str:
    by = {s["preset"].upper(): s for s in summaries}
    full = by.get("FULL", {})
    lines = [
        "## 4.2.2 Ablation 실험 결과",
        "",
        f"표 4는 검색·지식 구성요소별 ablation 결과이다. 실험 일자·폴더: `{exp_dir.name}`. "
        "스키마 검증·코드값 검증·질의-테이블 정합성 검증 적용 후 LLM 재시도 1회.",
        "",
        "**[표 4] Ablation별 NL→SQL 성능 비교**",
        "",
        "| 구성 (Preset) | 설명 | VS (%) | EX_exec (%) | Table F1 |",
        "|---------------|------|--------|-------------|----------|",
    ]
    desc = {
        "B0": "스키마 요약만",
        "B1": "+ ChromaDB RAG",
        "B2": "+ FK JOIN 힌트",
        "B3": "+ 온톨로지 개념 매핑",
        "FULL": "RAG + FK + 온톨로지 (제안)",
    }
    for p in PRESET_ORDER:
        s = by.get(p)
        if not s:
            continue
        star = "**" if p == "FULL" else ""
        lines.append(
            f"| {star}{p}{star} | {desc[p]} | {s['VS_pct']} | {s['EX_exec_pct']} | {s['Table_F1_avg']} |"
        )
    full_s = by.get("FULL", {})
    b2_s = by.get("B2", {})
    lines.extend([
        "",
        f"표 4에 따르면, 제안 구성(FULL)은 **VS {full_s.get('VS_pct', '?')}%**, "
        f"**EX_exec {full_s.get('EX_exec_pct', '?')}%**를 달성하였다. "
        f"B2(RAG+FK)는 EX_exec **{b2_s.get('EX_exec_pct', '?')}%**로 FK JOIN 힌트 기여가 크다. "
        "B1(RAG 단독)은 도메인·구조 지식 없이는 실행 정확도가 낮게 나타났다. "
        "EX_strict는 전 구성에서 0%에 가깝다(표현 차이).",
        "",
    ])
    return "\n".join(lines)


def patch_difficulty(exp_dir: Path) -> str:
    full_csv = exp_dir / sorted(exp_dir.glob("run_FULL_*.csv"))[-1].name
    full_path = exp_dir / full_csv
    import csv
    from eval.score import aggregate, load_gold, score_row

    gold = load_gold(GOLD)
    rows = list(csv.DictReader(full_path.open(encoding="utf-8-sig")))
    scored = [score_row(r, gold) for r in rows]
    by_diff = {}
    for s in scored:
        d = s.get("difficulty", "?")
        by_diff.setdefault(d, []).append(s)
    lines = [
        "## 4.2.3 난이도별 결과 (FULL)",
        "",
        "**[표 5] 난이도별 성능 (FULL, n=50)**",
        "",
        "| 난이도 | 문항 수 (n) | VS (%) | EX_exec (%) |",
        "|--------|-------------|--------|-------------|",
    ]
    for d in ("easy", "medium", "hard"):
        if d not in by_diff:
            continue
        agg = aggregate(by_diff[d])
        lines.append(
            f"| {d.capitalize()} | {agg['n']} | {agg['VS_pct']} | {agg['EX_exec_pct']} |"
        )
    lines.append("")
    return "\n".join(lines)


def update_paper_full(exp_dir: Path, summaries: list[dict]):
    draft = EVAL / "PAPER_SECTION_4_3_DRAFT.md"
    text = draft.read_text(encoding="utf-8")
    new_ablation = patch_section_43(summaries, exp_dir)
    new_diff = patch_difficulty(exp_dir)

    text = re.sub(
        r"## 4\.3\.2 Ablation 실험 결과[\s\S]*?(?=## 4\.3\.3)",
        new_ablation.replace("4.3.2", "4.3.2") + "\n---\n\n",
        text,
        count=1,
    )
    # also handle 4.2.2 from merge
    text = re.sub(
        r"## 4\.3\.3 난이도별[\s\S]*?(?=## 4\.3\.4)",
        new_diff.replace("4.2.3", "4.3.3") + "\n---\n\n",
        text,
        count=1,
    )
    draft.write_text(text, encoding="utf-8")

    # abstract snippet in PAPER_FULL - run merge after
    by = {s["preset"].upper(): s for s in summaries}
    full = by.get("FULL", {})
    abs_vs = full.get("VS_pct", "—")
    abs_ex = full.get("EX_exec_pct", "—")
    note = (
        f"\n\n<!-- experiment {exp_dir.name}: FULL VS={abs_vs}% EX_exec={abs_ex}% -->\n"
    )
    merge_note = EVAL / "LATEST_EXPERIMENT.txt"
    merge_note.write_text(
        f"experiment_dir={exp_dir}\nFULL_VS={abs_vs}\nFULL_EX_exec={abs_ex}\n"
        + json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Updated {draft}")
    print(f"Summary: {merge_note}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("experiment_dir", type=Path)
    args = p.parse_args()
    exp = args.experiment_dir if args.experiment_dir.is_absolute() else ROOT / args.experiment_dir
    summaries = load_summaries(exp)
    build_markdown(summaries, exp)
    update_paper_full(exp, summaries)
    # merge + docx
    import subprocess
    subprocess.run([sys.executable, str(EVAL / "merge_paper_sections.py")], cwd=str(ROOT), check=True)
    # patch PAPER_FULL abstract numbers
    full_draft = EVAL / "PAPER_FULL_DRAFT.md"
    text = full_draft.read_text(encoding="utf-8")
    by = {s["preset"].upper(): s for s in summaries}
    f = by.get("FULL", {})
    text = re.sub(
        r"\*\*유효 SQL 비율\(VS\) \d+%\*\*",
        f"**유효 SQL 비율(VS) {f.get('VS_pct', '?')}%**",
        text,
        count=1,
    )
    text = re.sub(
        r"\*\*실행 정확도\(EX_exec\) \d+%\*\*",
        f"**실행 정확도(EX_exec) {f.get('EX_exec_pct', '?')}%**",
        text,
        count=1,
    )
    text = re.sub(
        r"FK JOIN 힌트만 추가한 B2는 EX_exec \d+%",
        f"FK JOIN 힌트만 추가한 B2는 EX_exec {by.get('B2', {}).get('EX_exec_pct', '?')}%",
        text,
        count=1,
    )
    full_draft.write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, str(EVAL / "make_paper_full_docx.py")], cwd=str(ROOT), check=True)
    print("Done: merge + PAPER_FULL + docx")


if __name__ == "__main__":
    main()
