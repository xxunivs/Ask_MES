"""
SQL 실행을 원격 MES API 에 위임하는 클라이언트.

과거에는 팀원 PC 에서 Cloudflare 터널로 띄우던 mes-api(:8000) 의
POST /api/mes/query 를 호출했으나, 해당 서비스는 더 이상 없다.
현재는 배포된 NeuroFactory API 의 POST /chat/sql-execute 를 사용한다.
응답 형태({success, columns, rows, count})는 양쪽이 동일하다.
"""
import httpx
from core.config import MES_API_URL, MES_API_KEY

# 서버가 python 계열 기본 User-Agent 를 봇으로 보고 403 을 준다.
_HEADERS = {
    "X-API-Key": MES_API_KEY,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
}


async def execute_sql(sql: str, limit: int = 100) -> dict:
    """
    POST {MES_API_URL}/chat/sql-execute 호출
    반환: { success, count, columns, rows }
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{MES_API_URL}/chat/sql-execute",
            json={"sql": sql, "limit": limit},
            headers=_HEADERS,
        )
        resp.raise_for_status()
        return resp.json()
