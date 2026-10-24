from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal

import httpx

from app.config import DB_BACKEND, MES_API_KEY, MES_API_URL
from app.execution import sqlite_db
from app.execution.demo_db import connect_reader

# python 기본 User-Agent 는 원격 서버가 봇으로 보고 403 반환
_HEADERS = {
    "X-API-Key": MES_API_KEY,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
}


async def execute_sql(sql: str, limit: int = 100) -> dict:
    """DB 오류는 빈 결과(0행)로 오인되지 않도록 예외 발생"""
    if DB_BACKEND == "mes_api":
        return await _execute_remote(sql, limit)
    if DB_BACKEND == "sqlite":
        return await asyncio.to_thread(_execute_sqlite, sql, limit)
    return await asyncio.to_thread(_execute_demo, sql, limit)


def _to_json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _execute_demo(sql: str, limit: int) -> dict:
    with connect_reader() as conn:
        cur = conn.cursor()
        try:
            cur.execute(sql)
        except Exception as e:
            raise RuntimeError(f"DB 오류: {e}") from e
        columns = [d[0] for d in cur.description or []]
        rows = [{c: _to_json(v) for c, v in zip(columns, r)} for r in cur.fetchmany(limit)]
    return {"success": True, "count": len(rows), "columns": columns, "rows": rows}


def _execute_sqlite(sql: str, limit: int) -> dict:
    conn = sqlite_db.connect()
    try:
        cur = conn.execute(sqlite_db.translate(sql))
        columns = [d[0] for d in cur.description or []]
        rows = [{c: _to_json(v) for c, v in zip(columns, r)} for r in cur.fetchmany(limit)]
    except Exception as e:
        raise RuntimeError(f"DB 오류: {e}") from e
    finally:
        conn.close()
    return {"success": True, "count": len(rows), "columns": columns, "rows": rows}


async def _execute_remote(sql: str, limit: int) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{MES_API_URL}/chat/sql-execute",
            json={"sql": sql, "limit": limit},
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    # DB 오류도 HTTP 200 과 {"success": false} 본문으로 오므로 예외로 전환
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(data.get("error") or "SQL 실행 실패 (원인 미상)")
    return data
