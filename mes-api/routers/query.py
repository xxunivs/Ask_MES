from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from database import get_connection
from safety import validate_query, MAX_ROWS
import os

router = APIRouter()

# API Key 인증
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=401, detail="인증 실패: API Key가 올바르지 않습니다.")
    return api_key


class QueryRequest(BaseModel):
    sql: str
    limit: int = 100  # 기본 100행, 최대 MAX_ROWS


@router.post("/query")
def execute_query(
    request: QueryRequest,
    _: str = Depends(verify_api_key)
):
    # 1. Safety 검사
    is_valid, error_msg = validate_query(request.sql)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 2. limit 범위 제한
    limit = min(request.limit, MAX_ROWS)

    # 3. TOP 구문 자동 추가 (이미 TOP 있으면 스킵)
    sql = request.sql.strip()
    sql_lower = sql.lower()
    if "top " not in sql_lower and "fetch next" not in sql_lower:
        # SELECT 다음에 TOP N 삽입
        sql = re.sub(r"(?i)^(select\s)", f"SELECT TOP {limit} ", sql, count=1)

    # 4. DB 실행
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 오류: {str(e)}")

    return {
        "success": True,
        "count": len(rows),
        "columns": columns,
        "rows": rows
    }
