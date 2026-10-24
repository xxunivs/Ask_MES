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

from app.execution.sql_executor import execute_sql  # noqa: E402
from app.validation.code_values import (  # noqa: E402
    DEFAULT_FORBIDDEN_YN,
    load_profile_columns,
    save_code_values,
)


# 실제 MES API: TOP 없는 DISTINCT 오류, GROUP BY 사용
async def fetch_values(table: str, column: str, limit: int = 50) -> list[str]:
    sql = (
        f"SELECT TOP {limit} {column} AS v FROM {table} WITH (NOLOCK) "
        f"WHERE {column} IS NOT NULL GROUP BY {column} ORDER BY {column}"
    )
    rows = (await execute_sql(sql, limit=limit)).get("rows") or []
    return [str(r["v"]).strip() for r in rows if r.get("v") is not None and str(r["v"]).strip()]


def forbidden_for(values: list[str]) -> list[str]:
    if {v.upper() for v in values} <= {"Y", "N"}:
        return list(DEFAULT_FORBIDDEN_YN)
    return ["TRUE", "FALSE", "true", "false"]


async def main_async(dry_run: bool) -> int:
    profile = load_profile_columns()
    if not profile:
        print("mes_code_profile.json 에 대상 컬럼 없음")
        return 1

    column_values: dict[str, dict] = {}
    errors = 0
    for item in profile:
        key = f"{item['table'].upper()}.{item['column'].upper()}"
        try:
            values = await fetch_values(item["table"].upper(), item["column"].upper())
        except Exception as e:
            print(f"{key}: 실패 ({e})")
            errors += 1
            continue
        print(f"{key}: {len(values)}개 {values[:8]}")
        column_values[key] = {
            "label": item.get("label") or item["column"],
            "values": values,
            "forbidden_literals": forbidden_for(values),
        }

    if not dry_run:
        print(f"\n저장: {save_code_values(column_values)} ({len(column_values)}개 컬럼, 실패 {errors})")
    return 0 if errors == 0 else 2


def main():
    parser = argparse.ArgumentParser(description="코드값 수집 (mes_code_profile.json 대상 컬럼)")
    parser.add_argument("--dry-run", action="store_true", help="조회만 하고 저장하지 않음")
    raise SystemExit(asyncio.run(main_async(parser.parse_args().dry_run)))


if __name__ == "__main__":
    main()
