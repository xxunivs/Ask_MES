import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen35-9b"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = LLM_MODEL

VLLM_API_URL = os.getenv("VLLM_API_URL", "http://127.0.0.1:8008/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")

# "demo" 는 로컬 데모 DB(가상 데이터), "mes_api" 는 원격 MES API(실제 DB)
DB_BACKEND = os.getenv("DB_BACKEND", "demo").strip().lower()

# DB_BACKEND=mes_api 일 때의 원격 MES API
MES_API_URL = os.getenv("MES_API_URL", "http://localhost:8000")
MES_API_KEY = os.getenv("MES_API_KEY", "my-secret-api-key")

CHROMA_PATH = os.getenv("CHROMA_PATH", "./vector_index")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))

# Chroma 기본 임베딩(all-MiniLM-L6-v2)은 영어 전용이라 한국어 검색 불가, 다국어 bge-m3 사용
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
# "ollama" 는 OLLAMA_URL 의 /api/embeddings 사용, "default" 는 Chroma 기본 임베딩(대조군용)
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "ollama")

# docker compose 의 mes-db, 가상 데이터
DEMO_DB_HOST = os.getenv("DEMO_DB_HOST", "localhost")
DEMO_DB_PORT = int(os.getenv("DEMO_DB_PORT", "1433"))
DEMO_DB_USER = os.getenv("DEMO_DB_USER", "sa")
DEMO_DB_PASSWORD = os.getenv("DEMO_DB_PASSWORD", "")
DEMO_DB_NAME = os.getenv("DEMO_DB_NAME", "MES_DEMO")
# SQL 실행용 읽기 전용 계정 (demo-db/02_create_reader.sql)
DEMO_DB_READER_USER = os.getenv("DEMO_DB_READER_USER", "mes_reader")
DEMO_DB_READER_PASSWORD = os.getenv("DEMO_DB_READER_PASSWORD", "")
