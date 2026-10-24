from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import CORS_ORIGINS
from app.routers import chat, data
from app.retrieval.retriever import init_chroma


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Startup] ChromaDB 초기화 중...")
    init_chroma()
    print("[Startup] 완료, Ask MES! API 준비됨")
    yield


app = FastAPI(
    title="Ask MES! API",
    description="자연어 질문을 SQL로 바꿔 MES 데이터를 조회하는 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(data.router, prefix="/data", tags=["Data"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "Ask MES! API"}
