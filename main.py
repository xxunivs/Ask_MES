from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routers import chat
from core.retriever import init_chroma


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 ChromaDB 초기화 & 스키마 시딩
    print("[Startup] ChromaDB 초기화 중...")
    init_chroma()
    print("[Startup] 완료 — MES LLM API 준비됨")
    yield


app = FastAPI(
    title="MES LLM API",
    description="NeuroFactory NL→SQL (LangChain + ChromaDB + Ollama)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 운영 시 특정 도메인으로 제한
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/chat", tags=["Chat"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "MES LLM API"}
