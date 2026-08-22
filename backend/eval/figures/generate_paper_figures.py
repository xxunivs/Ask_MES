"""
논문용 figure PNG 생성 (matplotlib)

Usage (mes-llm-api 루트):
  python eval/figures/generate_paper_figures.py
  python eval/figures/generate_paper_figures.py --experiment eval/results/experiment_20260603_182753
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

EVAL = Path(__file__).resolve().parent.parent
FIG_DIR = Path(__file__).resolve().parent
DEFAULT_EXP = EVAL / "results" / "experiment_20260603_182753"
GOLD = EVAL.parent / "data" / "benchmark" / "mes_nl2sql_gold_v2.jsonl"

C_BLUE = "#1F497D"
C_BLUE2 = "#2E74B5"
C_ACCENT = "#C55A11"
C_GREEN = "#548235"
C_GRAY = "#7F7F7F"


def setup_font():
    for fam in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
        try:
            plt.rcParams["font.family"] = fam
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue


def save(fig, name: str):
    path = FIG_DIR / name
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  -> {path.name}")


def fig1_system_architecture():
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4)
    ax.axis("off")

    boxes = [
        (0.3, 1.4, 1.5, 1.2, "한국어\n자연어 질의", "#E7EEF7"),
        (2.1, 1.4, 1.5, 1.2, "① Ontology\n개념 매핑", "#D6E4F0"),
        (3.9, 1.4, 1.5, 1.2, "② ChromaDB\nRAG", "#D6E4F0"),
        (5.7, 1.4, 1.5, 1.2, "③ FK Path\nJOIN 힌트", "#D6E4F0"),
        (7.5, 1.4, 1.5, 1.2, "④ LLM\nQwen2.5:7b", "#D6E4F0"),
        (2.1, 0.15, 6.9, 0.95, "Hybrid RAG 컨텍스트 → SQL 프롬프트", "#F2F2F2"),
        (2.1, 2.85, 3.2, 0.75, "스키마·코드값·정합성 검증", "#FFF2CC"),
        (5.6, 2.85, 3.4, 0.75, "MES DB API 실행 (SELECT)", "#E2EFDA"),
    ]
    for x, y, w, h, label, color in boxes:
        rect = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.2, edgecolor=C_BLUE, facecolor=color,
        )
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=9, color="#333")

    for x1, x2, y in [(1.8, 2.1, 2.0), (3.6, 3.9, 2.0), (5.4, 5.7, 2.0), (7.2, 7.5, 2.0), (8.25, 8.25, 2.65)]:
        ax.add_patch(FancyArrowPatch(
            (x1, y), (x2, y), arrowstyle="-|>", mutation_scale=12,
            color=C_BLUE2, linewidth=1.5,
        ))
    ax.add_patch(FancyArrowPatch((8.25, 2.0), (8.25, 2.65), arrowstyle="-|>", mutation_scale=12, color=C_BLUE2, linewidth=1.5))
    ax.add_patch(FancyArrowPatch((5.5, 1.1), (5.5, 1.4), arrowstyle="-|>", mutation_scale=12, color=C_GRAY, linewidth=1.2))
    ax.text(5.0, 3.75, "NeuroFactory NL→SQL 파이프라인", fontsize=13, fontweight="bold", color=C_BLUE, ha="center")
    save(fig, "fig1_system_architecture.png")


def load_benchmark_stats() -> dict:
    diff = {"easy": 0, "medium": 0, "hard": 0}
    qtype = {"list": 0, "filter": 0, "aggregate": 0, "timeseries": 0}
    join_y, join_n = 0, 0
    if not GOLD.exists():
        return {"diff": diff, "qtype": qtype, "join": (18, 32)}
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        d = str(row.get("difficulty", "")).lower()
        if d in diff:
            diff[d] += 1
        qt = str(row.get("query_type", "")).lower()
        if qt in qtype:
            qtype[qt] += 1
        if row.get("requires_join"):
            join_y += 1
        else:
            join_n += 1
    return {"diff": diff, "qtype": qtype, "join": (join_y, join_n)}


def fig2_benchmark_distribution():
    stats = load_benchmark_stats()
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))

    labels = ["Easy", "Medium", "Hard"]
    vals = [stats["diff"]["easy"], stats["diff"]["medium"], stats["diff"]["hard"]]
    colors = [C_BLUE2, C_BLUE, C_ACCENT]
    bars = axes[0].bar(labels, vals, color=colors, edgecolor="white", linewidth=0.8)
    axes[0].set_ylabel("문항 수")
    axes[0].set_title("(a) 난이도 분포 (n=50)", fontsize=11, fontweight="bold", color=C_BLUE)
    axes[0].set_ylim(0, max(vals) * 1.25 if vals else 25)
    for b, v in zip(bars, vals):
        axes[0].text(b.get_x() + b.get_width() / 2, v + 0.5, str(v), ha="center", fontsize=10)

    qlabels = ["목록", "필터", "집계", "시계열"]
    qvals = [
        stats["qtype"]["list"], stats["qtype"]["filter"],
        stats["qtype"]["aggregate"], stats["qtype"]["timeseries"],
    ]
    bars2 = axes[1].bar(qlabels, qvals, color=[C_GREEN, C_BLUE2, C_ACCENT, C_GRAY], edgecolor="white")
    axes[1].set_ylabel("문항 수")
    axes[1].set_title("(b) 질의 유형 분포", fontsize=11, fontweight="bold", color=C_BLUE)
    axes[1].set_ylim(0, max(qvals) * 1.25 if qvals else 20)
    for b, v in zip(bars2, qvals):
        axes[1].text(b.get_x() + b.get_width() / 2, v + 0.4, str(v), ha="center", fontsize=10)

    fig.suptitle("MES-NL2SQL-Gold v2 벤치마크 구성", fontsize=12, fontweight="bold", color=C_BLUE, y=1.02)
    fig.tight_layout()
    save(fig, "fig2_benchmark_distribution.png")


def fig3_ablation_results(exp_dir: Path):
    summary_path = exp_dir / "ablation_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    rows = json.loads(summary_path.read_text(encoding="utf-8"))
    presets = [r["preset"] for r in rows]
    ex = [r["EX_exec_pct"] for r in rows]
    f1 = [r["Table_F1_avg"] * 100 for r in rows]

    fig, ax1 = plt.subplots(figsize=(8, 4.2))
    x = range(len(presets))
    w = 0.38
    bars = ax1.bar([i - w / 2 for i in x], ex, width=w, label="EX_exec (%)", color=C_BLUE2, edgecolor="white")
    ax1.set_ylabel("EX_exec (%)", color=C_BLUE2)
    ax1.set_ylim(0, 100)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(presets)
    for b, v in zip(bars, ex):
        ax1.text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.0f}", ha="center", fontsize=9, color=C_BLUE2)

    ax2 = ax1.twinx()
    ax2.plot(list(x), f1, color=C_ACCENT, marker="o", linewidth=2, markersize=8, label="Table F1 (×100)")
    ax2.set_ylabel("Table F1 (×100)", color=C_ACCENT)
    ax2.set_ylim(60, 85)
    for i, v in enumerate(f1):
        ax2.text(i, v + 1.2, f"{v/100:.3f}", ha="center", fontsize=8, color=C_ACCENT)

    ax1.set_title("Ablation별 실행 정확도 및 Table F1", fontsize=12, fontweight="bold", color=C_BLUE)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.axhline(60, color=C_GREEN, linestyle="--", linewidth=0.8, alpha=0.6)
    fig.tight_layout()
    save(fig, "fig3_ablation_ex_exec.png")


def fig4_difficulty_full(exp_dir: Path):
    import csv

    csvs = list(exp_dir.glob("run_FULL_*.csv"))
    if not csvs:
        raise FileNotFoundError(f"FULL csv in {exp_dir}")
    path = sorted(csvs)[-1]

    groups: dict[str, list[bool]] = {"easy": [], "medium": [], "hard": []}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            d = str(row.get("difficulty", "")).lower()
            if d not in groups:
                continue
            ok = str(row.get("exec_ok", "")).lower() in ("true", "1", "yes")
            gold_ok = str(row.get("gold_exec_ok", "")).lower() in ("true", "1", "yes")
            groups[d].append(ok and gold_ok)

    labels, rates, ns = [], [], []
    for key, title in [("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")]:
        arr = groups[key]
        if not arr:
            continue
        labels.append(title)
        ns.append(len(arr))
        rates.append(100.0 * sum(arr) / len(arr))

    fig, ax = plt.subplots(figsize=(6.5, 4))
    colors = [C_BLUE2, C_GREEN, C_ACCENT]
    bars = ax.bar(labels, rates, color=colors[: len(labels)], edgecolor="white")
    ax.set_ylabel("EX_exec (%)")
    ax.set_ylim(0, 100)
    ax.set_title("FULL 구성 난이도별 실행 정확도", fontsize=12, fontweight="bold", color=C_BLUE)
    for b, r, n in zip(bars, rates, ns):
        ax.text(b.get_x() + b.get_width() / 2, r + 2, f"{r:.1f}%\n(n={n})", ha="center", fontsize=10)
    fig.tight_layout()
    save(fig, "fig4_difficulty_full.png")


def fig5_error_breakdown(exp_dir: Path):
    import csv
    import re

    csvs = list(exp_dir.glob("run_FULL_*.csv"))
    if not csvs:
        return
    path = sorted(csvs)[-1]
    cats = {
        "스키마 환각": 0,
        "테이블/컬럼 혼동": 0,
        "날짜·집계 규칙": 0,
        "기타 실행 오류": 0,
    }
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ok = str(row.get("exec_ok", "")).lower() in ("true", "1", "yes")
            gold_ok = str(row.get("gold_exec_ok", "")).lower() in ("true", "1", "yes")
            if ok and gold_ok:
                continue
            err = (row.get("db_error") or "") + (row.get("pred_sql") or "")
            err_low = err.lower()
            if re.search(r"invalid object|does not exist|unknown column", err_low):
                if "cim_material" in err_low or "cim_equipmentstate" in err_low:
                    cats["스키마 환각"] += 1
                else:
                    cats["테이블/컬럼 혼동"] += 1
            elif "date" in err_low or row.get("id") == "Q020":
                cats["날짜·집계 규칙"] += 1
            else:
                cats["기타 실행 오류"] += 1

    if sum(cats.values()) == 0:
        return

    fig, ax = plt.subplots(figsize=(6, 4))
    labels = list(cats.keys())
    vals = [cats[k] for k in labels]
    colors = [C_ACCENT, C_BLUE, C_GREEN, C_GRAY]
    wedges, texts, autotexts = ax.pie(
        vals, labels=labels, autopct="%1.0f%%", startangle=90,
        colors=colors[: len(labels)], textprops={"fontsize": 9},
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title("FULL 실행 실패 유형 분포 (n=20)", fontsize=11, fontweight="bold", color=C_BLUE)
    fig.tight_layout()
    save(fig, "fig5_error_breakdown.png")


def main():
    setup_font()
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXP)
    args = parser.parse_args()
    exp = args.experiment.resolve()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    print("[figures] 생성 중...")
    fig1_system_architecture()
    fig2_benchmark_distribution()
    fig3_ablation_results(exp)
    fig4_difficulty_full(exp)
    fig5_error_breakdown(exp)
    print(f"[figures] 완료 → {FIG_DIR}")


if __name__ == "__main__":
    main()
