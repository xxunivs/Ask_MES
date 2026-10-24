"""
/chat 라우터
  POST /chat/nl-to-sql : 자연어 질문 -> SQL 생성 -> DB 실행 (app/core/pipeline.py)
  GET  /chat/health    : LLM 연결 상태 확인
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import LLM_MODEL, LLM_PROVIDER
from app.core.llm import check_ollama
from app.core.pipeline import run_pipeline

router = APIRouter()


class NlToSqlRequest(BaseModel):
    question: str
    limit: int = 100


@router.post("/nl-to-sql")
async def nl_to_sql(req: NlToSqlRequest):
    """질문의 SQL 생성 및 실행, success 는 DB 실행까지의 성공 여부"""
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
