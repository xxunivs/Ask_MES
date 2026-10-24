"""
데모 SQL Server -> 배포용 SQLite 파일

실행 방법 (backend/ 에서, 데모 DB 를 띄운 상태):
  ./venv/bin/python ../synthetic_data/export_sqlite.py
결과: backend/data/mes_demo.sqlite (배포용 데모 DB)
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import SQLITE_PATH  # noqa: E402
from app.execution.demo_db import connect  # noqa: E402

_NUMERIC = {
    "int": "INTEGER",
    "bigint": "INTEGER",
    "smallint": "INTEGER",
    "tinyint": "INTEGER",
    "bit": "INTEGER",
    "decimal": "REAL",
    "numeric": "REAL",
    "float": "REAL",
    "real": "REAL",
    "money": "REAL",
}


def _value(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def main():
    out = Path(SQLITE_PATH).resolve()
    out.unlink(missing_ok=True)
    src = connect()
    cur = src.cursor()
    cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
    tables = [r[0] for r in cur.fetchall()]

    dst = sqlite3.connect(out)
    total = 0
    for table in tables:
        cur.execute(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (table,),
        )
        cols = cur.fetchall()
        # 문자열 컬럼 NOCASE (SQL Server 데모 DB 와 같은 대소문자 무시)
        col_defs = ", ".join(
            f'"{name}" {_NUMERIC[dtype]}' if dtype in _NUMERIC else f'"{name}" TEXT COLLATE NOCASE'
            for name, dtype in cols
        )
        dst.execute(f'CREATE TABLE "{table}" ({col_defs})')
        cur.execute(f"SELECT * FROM {table}")
        rows = [tuple(_value(v) for v in r) for r in cur.fetchall()]
        dst.executemany(f'INSERT INTO "{table}" VALUES ({", ".join("?" * len(cols))})', rows)
        total += len(rows)
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    print(f"{len(tables)}개 표, {total}행 -> {out} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
