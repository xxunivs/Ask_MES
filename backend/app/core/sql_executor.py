"""
생성된 SQL 실행

DB_BACKEND 설정에 따라 둘 중 하나로 실행한다.
  demo    : 로컬 데모 DB(가상 데이터)에 읽기 전용 계정으로 직접 실행
  mes_api : 원격 MES API(실제 DB)의 POST /chat/sql-execute 로 위임
반환 형태는 같다: { success, columns, rows, count }
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal

import httpx

from app.core.config import DB_BACKEND, MES_API_KEY, MES_API_URL
from app.core.demo_db import connect_reader

# 원격 서버가 python 계열 기본 User-Agent 를 봇으로 보고 403 을 준다.
_HEADERS = {
    "X-API-Key": MES_API_KEY,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
}


async def execute_sql(sql: str, limit: int = 100) -> dict:
    """
    SQL 실행 후 { success, count, columns, rows } 반환

    DB 오류는 예외로 올린다. 실패를 빈 결과로 돌려주면 호출부가
    "실행됐는데 0행"으로 오해하기 때문이다.
    """
    if DB_BACKEND == "mes_api":
        return await _execute_remote(sql, limit)
    return await asyncio.to_thread(_execute_demo, sql, limit)


def _to_json(value):
    """JSON 으로 보낼 수 있는 값으로 변환"""
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


async def _execute_remote(sql: str, limit: int) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{MES_API_URL}/chat/sql-execute",
            json={"sql": sql, "limit": limit},
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    # DB 문법 오류여도 HTTP 는 200 이고 본문이 {"success": false, "error": ...} 로 온다.
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(data.get("error") or "SQL 실행 실패 (원인 미상)")
    return data
