from __future__ import annotations

from collections import OrderedDict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import DB_BACKEND, LLM_MODEL, LLM_PROVIDER
from app.generation.llm import check_llm
from app.pipeline import run_pipeline

router = APIRouter()

# 가상 데이터(SQLite)는 고정이라 같은 질문의 성공 결과를 재사용, 실제 DB 에서는 끔
_CACHE_ENABLED = DB_BACKEND == "sqlite"
_CACHE_MAX = 256
_cache: OrderedDict[tuple[str, int], dict] = OrderedDict()


class NlToSqlRequest(BaseModel):
    question: str
    limit: int = Field(100, ge=1, le=1000)


@router.post("/nl-to-sql")
async def nl_to_sql(req: NlToSqlRequest):
    key = (" ".join(req.question.split()), req.limit)
    if _CACHE_ENABLED and key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    try:
        result = await run_pipeline(req.question, limit=req.limit)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"질문 처리 오류: {e}")

    error = result.db_error or ("" if result.schema_valid else f"SQL 검증 실패: {result.schema_error}")
    response = {
        "success": result.executed,
        "sql": result.sql,
        "data": result.data,
        "db_error": error or None,
        "trace": result.trace,
    }
    if _CACHE_ENABLED and result.executed:
        _cache[key] = response
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return response


@router.get("/health")
async def chat_health():
    llm_ok = await check_llm()
    return {
        "provider": LLM_PROVIDER,
        "llm": "ok" if llm_ok else "연결 실패",
        "model": LLM_MODEL,
    }
