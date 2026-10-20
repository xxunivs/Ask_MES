"""
공개용 데모 DB(가상 데이터) 접속
"""
from __future__ import annotations

import pymssql

from app.core.config import (
    DEMO_DB_HOST,
    DEMO_DB_NAME,
    DEMO_DB_PASSWORD,
    DEMO_DB_PORT,
    DEMO_DB_READER_PASSWORD,
    DEMO_DB_READER_USER,
    DEMO_DB_USER,
)


def connect() -> pymssql.Connection:
    """관리자 계정 접속 (데이터 생성, 진행 현황용)"""
    return pymssql.connect(
        server=DEMO_DB_HOST,
        port=DEMO_DB_PORT,
        user=DEMO_DB_USER,
        password=DEMO_DB_PASSWORD,
        database=DEMO_DB_NAME,
        login_timeout=5,
    )


def connect_reader() -> pymssql.Connection:
    """읽기 전용 계정 접속 (LLM 생성 SQL 실행용)"""
    return pymssql.connect(
        server=DEMO_DB_HOST,
        port=DEMO_DB_PORT,
        user=DEMO_DB_READER_USER,
        password=DEMO_DB_READER_PASSWORD,
        database=DEMO_DB_NAME,
        login_timeout=5,
    )


def table_row_counts() -> dict[str, int]:
    """표별 행 수 (sys.partitions 기준, 전체 스캔 없음)"""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT t.name, SUM(p.rows) FROM sys.tables t "
            "JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1) "
            "GROUP BY t.name"
        )
        return {name: int(rows) for name, rows in cur.fetchall()}
