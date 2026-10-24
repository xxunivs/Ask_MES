from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import LLM_MODEL, LLM_PROVIDER
from app.generation.llm import check_ollama
from app.pipeline import run_pipeline

router = APIRouter()


class NlToSqlRequest(BaseModel):
    question: str
    limit: int = 100


@router.post("/nl-to-sql")
async def nl_to_sql(req: NlToSqlRequest):
    try:
        result = await run_pipeline(req.question, limit=req.limit)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM 연결 오류: {e}")

    error = result.db_error or ("" if result.schema_valid else f"SQL 검증 실패: {result.schema_error}")
    return {
        "success": result.executed,
        "sql": result.sql,
        "data": result.data,
        "db_error": error or None,
        "trace": result.trace,
    }


@router.get("/health")
async def chat_health():
    llm_ok = await check_ollama()
    return {
        "provider": LLM_PROVIDER,
        "llm": "ok" if llm_ok else "연결 실패",
        "model": LLM_MODEL,
    }
