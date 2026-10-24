"""
실행 방법 (backend/ 에서, .env 의 DB 설정 필요):
  python scripts/collect_code_values.py
  python scripts/collect_code_values.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.validation.code_values import (  # noqa: E402
    DEFAULT_FORBIDDEN_YN,
    load_profile_columns,
    save_code_values,
)
from app.execution.sql_executor import execute_sql  # noqa: E402


async def fetch_distinct(table: str, column: str, limit: int = 50) -> list[str]:
    sql = (
        f"SELECT DISTINCT TOP {limit} {column} AS v "
        f"FROM {table} WITH (NOLOCK) "
        f"WHERE {column} IS NOT NULL "
        f"ORDER BY {column}"
    )
    res = await execute_sql(sql, limit=limit)
    rows = res.get("rows") or []
    values: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            v = row.get("v") or row.get(column) or next(iter(row.values()), None)
        elif isinstance(row, (list, tuple)) and row:
            v = row[0]
        else:
            v = row
        if v is not None and str(v).strip() != "":
            values.append(str(v).strip())
    return values


def build_forbidden(values: list[str]) -> list[str]:
    upper = {v.upper() for v in values}
    if upper <= {"Y", "N"} or upper == {"Y"} or upper == {"N"}:
        return list(DEFAULT_FORBIDDEN_YN)
    return ["TRUE", "FALSE", "true", "false"]


async def main_async(dry_run: bool) -> int:
    profile = load_profile_columns()
    if not profile:
        print("mes_code_profile.json 에 columns 가 없습니다.")
        return 1

    column_values: dict[str, dict] = {}
    errors = 0

    for item in profile:
        table = item["table"].upper()
        column = item["column"].upper()
        key = f"{table}.{column}"
        label = item.get("label") or column
        print(f"[collect] {key} ...", end=" ", flush=True)

        try:
            values = await fetch_distinct(table, column)
        except Exception as e:
            print(f"FAIL ({e})")
            errors += 1
            continue

        print(f"OK ({len(values)} values: {values[:8]}{'...' if len(values) > 8 else ''})")
        column_values[key] = {
            "label": label,
            "values": values,
            "forbidden_literals": build_forbidden(values),
        }

    if dry_run:
        print("\n[dry-run] 파일 저장 생략")
        return 0 if not errors else 2

    path = save_code_values(column_values)
    print(f"\n저장 완료: {path} ({len(column_values)} 컬럼, errors={errors})")
    print("ChromaDB 반영: vector_index 삭제 후 서버 재시작 또는 mes_schema.json touch")
    return 0 if errors == 0 else 2


def main():
    p = argparse.ArgumentParser(description="MES 코드값 DISTINCT 수집")
    p.add_argument("--dry-run", action="store_true", help="API만 호출, JSON 저장 안 함")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main_async(args.dry_run)))


if __name__ == "__main__":
    main()
