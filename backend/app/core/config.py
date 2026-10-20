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

# RAG 검색 결과 수. 논문 구성은 top-k=8.
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))

# 스키마 임베딩 모델. 논문 구성은 bge-m3(1024차원, 다국어).
# Chroma 기본 임베딩(all-MiniLM-L6-v2)은 영어 전용이라 한국어 질의에서 검색이 무너진다.
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
# 임베딩 백엔드: "ollama" 는 OLLAMA_URL 의 /api/embeddings 를 부른다.
# "default" 로 두면 Chroma 기본 임베딩으로 되돌아간다(대조군용).
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "ollama")
