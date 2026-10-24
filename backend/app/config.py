import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen35-9b"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = LLM_MODEL

VLLM_API_URL = os.getenv("VLLM_API_URL", "http://127.0.0.1:8008/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")

DB_BACKEND = os.getenv("DB_BACKEND", "demo").strip().lower()

MES_API_URL = os.getenv("MES_API_URL", "http://localhost:8000")
MES_API_KEY = os.getenv("MES_API_KEY", "my-secret-api-key")

CHROMA_PATH = os.getenv("CHROMA_PATH", "./vector_index")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))

EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "ollama")

DEMO_DB_HOST = os.getenv("DEMO_DB_HOST", "localhost")
DEMO_DB_PORT = int(os.getenv("DEMO_DB_PORT", "1433"))
DEMO_DB_USER = os.getenv("DEMO_DB_USER", "sa")
DEMO_DB_PASSWORD = os.getenv("DEMO_DB_PASSWORD", "")
DEMO_DB_NAME = os.getenv("DEMO_DB_NAME", "MES_DEMO")
DEMO_DB_READER_USER = os.getenv("DEMO_DB_READER_USER", "mes_reader")
DEMO_DB_READER_PASSWORD = os.getenv("DEMO_DB_READER_PASSWORD", "")
