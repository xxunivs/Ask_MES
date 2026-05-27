import os
from dotenv import load_dotenv

load_dotenv()

# Ollama 설정
OLLAMA_URL   = os.getenv("OLLAMA_URL",  "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# MES DB API (기존 mes-api) 설정
MES_API_URL = os.getenv("MES_API_URL", "http://localhost:8000")
MES_API_KEY = os.getenv("MES_API_KEY", "my-secret-api-key")

# ChromaDB 저장 경로
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")

# RAG 검색 결과 수
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "6"))
