from __future__ import annotations

import httpx
from app.core.config import (
    LLM_PROVIDER,
    LLM_MODEL,
    OLLAMA_URL,
    OLLAMA_MODEL,
    VLLM_API_URL,
    VLLM_API_KEY,
)


async def llm_generate(
    prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 512,
    seed: int | None = 0,
) -> str:
    """seed 는 재현성용 고정값, None 이면 비결정적"""
    if LLM_PROVIDER in {"vllm", "openai"}:
        return await _vllm_generate(prompt, temperature, max_tokens, seed)
    return await _ollama_generate(prompt, temperature, max_tokens, seed)


async def _ollama_generate(
    prompt: str, temperature: float, max_tokens: int, seed: int | None = 0
) -> str:
    options = {
        "temperature": temperature,
        "num_predict": max_tokens,
        # 스키마 컨텍스트(약 3천 토큰) 잘림 방지용 길이
        "num_ctx": 8192,
    }
    if seed is not None:
        options["seed"] = seed
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        # 응답 지연 방지용 Qwen thinking 모드 비활성화
        "think": False,
        "options": options,
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


async def _vllm_generate(
    prompt: str, temperature: float, max_tokens: int, seed: int | None = 0
) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if LLM_PROVIDER == "vllm":
        # SQL 출력에 불필요하고 지연과 토큰을 대부분 소모하는 Qwen thinking 모드 비활성화
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        if seed is not None:
            payload["seed"] = seed
    headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{VLLM_API_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.ReadTimeout:
        raise RuntimeError("vLLM 응답 타임아웃 (180초 초과) — 모델 로딩 중이거나 과부하 상태")
    except httpx.ConnectError:
        raise RuntimeError(f"vLLM 연결 실패 — {VLLM_API_URL} 서버 확인 필요")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"vLLM HTTP 오류: {e.response.status_code} — {e.response.text[:200]}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"vLLM 응답 파싱 실패: {e} — {data}")


async def check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if LLM_PROVIDER in {"vllm", "openai"}:
                resp = await client.get(
                    f"{VLLM_API_URL.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
                )
                return resp.status_code == 200
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False
