"""
기존 mes-api (port 8000) 에 SQL 실행을 위임하는 클라이언트
"""
import httpx
from core.config import MES_API_URL, MES_API_KEY


async def execute_sql(sql: str, limit: int = 100) -> dict:
    """
    mes-api POST /api/mes/query 호출
    반환: { success, count, columns, rows }
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{MES_API_URL}/api/mes/query",
            json={"sql": sql, "limit": limit},
            headers={"X-API-Key": MES_API_KEY},
        )
        resp.raise_for_status()
        return resp.json()
