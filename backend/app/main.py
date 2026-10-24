from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.retrieval.retriever import init_chroma
from app.routers import chat, data


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_chroma()
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
