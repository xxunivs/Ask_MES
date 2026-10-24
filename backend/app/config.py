import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:9b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VLLM_API_URL = os.getenv("VLLM_API_URL", "http://127.0.0.1:8008/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")

# 임베딩, 벡터 색인
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "ollama")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
CHROMA_PATH = os.getenv("CHROMA_PATH", "./vector_index")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))

# SQL 실행 대상
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()
SQLITE_PATH = os.getenv("SQLITE_PATH", str(DATA_DIR / "mes_demo.sqlite"))
MES_API_URL = os.getenv("MES_API_URL", "http://localhost:8000")
MES_API_KEY = os.getenv("MES_API_KEY", "")
DEMO_DB_HOST = os.getenv("DEMO_DB_HOST", "localhost")
DEMO_DB_PORT = int(os.getenv("DEMO_DB_PORT", "1433"))
DEMO_DB_USER = os.getenv("DEMO_DB_USER", "sa")
DEMO_DB_PASSWORD = os.getenv("DEMO_DB_PASSWORD", "")
DEMO_DB_NAME = os.getenv("DEMO_DB_NAME", "MES_DEMO")
DEMO_DB_READER_USER = os.getenv("DEMO_DB_READER_USER", "mes_reader")
DEMO_DB_READER_PASSWORD = os.getenv("DEMO_DB_READER_PASSWORD", "")

# 웹
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
