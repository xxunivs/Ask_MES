import os
from dotenv import load_dotenv

load_dotenv()

# LLM 설정
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen35-9b"))

# Ollama 설정
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = LLM_MODEL

# vLLM / OpenAI-compatible API 설정
VLLM_API_URL = os.getenv("VLLM_API_URL", "http://127.0.0.1:8008/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")

# MES DB API (기존 mes-api) 설정
MES_API_URL = os.getenv("MES_API_URL", "http://localhost:8000")
MES_API_KEY = os.getenv("MES_API_KEY", "my-secret-api-key")

# ChromaDB 저장 경로
CHROMA_PATH = os.getenv("CHROMA_PATH", "./vector_index")

# RAG 검색 결과 수
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "6"))
