"""
Ollama REST API 클라이언트
- /api/generate  : SQL 생성, 분석 텍스트 생성
- /api/embeddings: ChromaDB 임베딩 (선택 사용)
"""
import httpx
from core.config import OLLAMA_URL, OLLAMA_MODEL


async def llm_generate(prompt: str, temperature: float = 0.1, max_tokens: int = 512) -> str:
    """Ollama /api/generate 호출 → 응답 텍스트 반환"""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "response" not in data:
                raise ValueError(f"Ollama 응답에 'response' 키 없음: {data}")
            return data["response"].strip()
    except httpx.ReadTimeout:
        raise RuntimeError("Ollama 응답 타임아웃 (180초 초과) — 모델 로딩 중이거나 과부하 상태")
    except httpx.ConnectError:
        raise RuntimeError(f"Ollama 연결 실패 — {OLLAMA_URL} 서버 확인 필요")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama HTTP 오류: {e.response.status_code} — {e.response.text[:200]}")


async def check_ollama() -> bool:
    """Ollama 서버 연결 확인"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False
