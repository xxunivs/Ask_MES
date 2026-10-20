from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import query

app = FastAPI(
    title="MES DB API",
    description="YG-1 MES DB 조회 API (SELECT only)",
    version="1.0.0"
)

# CORS 설정 (NeuroFactory 프론트엔드 연동용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 운영 시 특정 도메인으로 제한 권장
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(query.router, prefix="/api/mes", tags=["MES Query"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "MES DB API"}
