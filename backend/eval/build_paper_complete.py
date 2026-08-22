"""
논문 완성본 일괄 생성: figure → MD 병합 → Word

Usage (mes-llm-api 루트):
  python eval/build_paper_complete.py
  python eval/build_paper_complete.py --experiment eval/results/experiment_20260603_182753
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    print(f"\n>>> {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(r.returncode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment",
        default="eval/results/experiment_20260603_182753",
        help="ablation 결과 폴더",
    )
    args = parser.parse_args()
    py = ROOT / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)

    run([str(py), "eval/figures/generate_paper_figures.py", "--experiment", args.experiment])
    run([str(py), "eval/merge_paper_sections.py"])
    run([str(py), "eval/make_paper_full_docx.py"])
    print("\n[완료] PAPER_FULL_DRAFT.md + figures/ + 논문초안_*.docx")


if __name__ == "__main__":
    main()
