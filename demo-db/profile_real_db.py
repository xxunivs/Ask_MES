"""
실제 기록, ID, 사람 이름 칸의 값은 미보관, 코드성 칸만 값 목록 보관

실행 방법 (backend/ 에서):
  ./venv/bin/python ../demo-db/profile_real_db.py
결과: demo-db/value_profile.md (요약, git 제외), demo-db/column_spec.json (칸 규칙, 실제 값 미포함)
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution.sql_executor import execute_sql  # noqa: E402

SAMPLE_ROWS = 2000
CODE_MAX_DISTINCT = 20
# 사람 이름, 자유 서술 가능 칸 (값 비공개)
PRIVATE_COLUMN = re.compile(r"USER|NAME|DESC|COMMENT|TEXT|NOTE|REMARK|EMAIL|PHONE", re.IGNORECASE)
OUTPUT = Path(__file__).resolve().parent / "value_profile.md"
SPEC_OUTPUT = Path(__file__).resolve().parent / "column_spec.json"
SAFE_CODE = re.compile(r"^[A-Za-z0-9_\-]{1,20}$")


def shape_of(value: str) -> str:
    value = re.sub(r"[가-힣]", "가", value)
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", value))


def describe(column: str, values: list) -> str:
    filled = [v for v in values if v not in (None, "")]
    empty = len(values) - len(filled)
    head = f"빈 값 {empty}/{len(values)}"
    if not filled:
        return head

    nums = [v for v in filled if isinstance(v, (int, float))]
    if len(nums) == len(filled):
        return f"{head}, 숫자 {min(nums)} ~ {max(nums)}"

    texts = [str(v) for v in filled]
    if all(re.match(r"\d{4}-\d{2}-\d{2}T", t) for t in texts):
        return f"{head}, 날짜 {min(texts)[:10]} ~ {max(texts)[:10]}"

    counts = Counter(texts)
    if len(counts) <= CODE_MAX_DISTINCT and not PRIVATE_COLUMN.search(column):
        top = ", ".join(f"`{v}`({n})" for v, n in counts.most_common())
        return f"{head}, 코드값 {len(counts)}종: {top}"

    shapes = Counter(shape_of(t) for t in texts).most_common(3)
    lengths = [len(t) for t in texts]
    shape_text = ", ".join(f"`{s}`" for s, _ in shapes) if not PRIVATE_COLUMN.search(column) else "(비공개 칸)"
    return f"{head}, 서로 다른 값 {len(counts)}종, 길이 {min(lengths)}~{max(lengths)}, 모양 {shape_text}"


def spec_of(column: str, values: list) -> dict:
    filled = [v for v in values if v not in (None, "")]
    spec: dict = {"empty_ratio": round(1 - len(filled) / max(len(values), 1), 3)}
    if not filled:
        return {**spec, "kind": "empty"}

    nums = [v for v in filled if isinstance(v, (int, float))]
    if len(nums) == len(filled):
        ordered = sorted(nums)
        return {**spec, "kind": "number", "integer": all(float(n).is_integer() for n in nums),
                "low": ordered[len(ordered) // 20], "high": ordered[len(ordered) * 19 // 20]}

    texts = [str(v) for v in filled]
    if all(re.match(r"\d{4}-\d{2}-\d{2}T", t) for t in texts):
        return {**spec, "kind": "date"}

    counts = Counter(texts)
    if (len(counts) <= CODE_MAX_DISTINCT and not PRIVATE_COLUMN.search(column)
            and all(SAFE_CODE.match(v) for v in counts)):
        return {**spec, "kind": "code", "values": dict(counts.most_common())}

    shapes = Counter(shape_of(t) for t in texts)
    return {**spec, "kind": "text", "distinct_ratio": round(len(counts) / len(texts), 3),
            "shapes": [s for s, _ in shapes.most_common(3)]}


async def profile_table(name: str) -> tuple[list[str], dict]:
    result = await execute_sql(f"SELECT TOP {SAMPLE_ROWS} * FROM {name} WITH (NOLOCK)", limit=SAMPLE_ROWS)
    rows, columns = result.get("rows", []), result.get("columns", [])
    lines = [f"## {name}", "", f"표본 {len(rows)}행, 칸 {len(columns)}개", "", "| 칸 | 특징 |", "|---|---|"]
    spec = {}
    for col in columns:
        values = [r.get(col) for r in rows]
        lines.append(f"| {col} | {describe(col, values)} |")
        spec[col] = spec_of(col, values)
    return lines + [""], spec


async def main() -> None:
    tables = await execute_sql(
        "SELECT DISTINCT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WITH (NOLOCK) WHERE TABLE_NAME LIKE 'CIM[_]%'", limit=1000
    )
    targets = [line.split("[")[1].split("]")[0] for line in
               (ROOT / "demo-db/01_create_tables.sql").read_text(encoding="utf-8").splitlines()
               if line.startswith("CREATE TABLE")]
    print(f"실제 DB CIM 표 {tables['count']}개 중 데모 대상 {len(targets)}개 조사")

    out = ["# 실제 MES DB 값 모양 조사", "",
           f"표마다 표본 {SAMPLE_ROWS}행 기준. 실제 기록과 ID 값은 남기지 않음.", ""]
    specs = {}
    for name in targets:
        print(f"  {name}")
        lines, specs[name] = await profile_table(name)
        out += lines
    OUTPUT.write_text("\n".join(out), encoding="utf-8")
    SPEC_OUTPUT.write_text(json.dumps(specs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"결과: {OUTPUT}, {SPEC_OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
