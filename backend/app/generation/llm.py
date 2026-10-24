from __future__ import annotations

import asyncio

import httpx

from app.config import DEEPINFRA_API_KEY, DEEPINFRA_URL, LLM_MODEL, LLM_PROVIDER, OLLAMA_URL, VLLM_API_KEY, VLLM_API_URL

_OPENAI_COMPATIBLE = {"vllm", "openai", "deepinfra"}
_TIMEOUT = 180.0

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


# 연결 재사용 (이벤트 루프가 바뀌면 새로 생성)
def _shared_client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        _client, _client_loop = httpx.AsyncClient(timeout=_TIMEOUT), loop
    return _client


def _openai_endpoint() -> tuple[str, str]:
    if LLM_PROVIDER == "deepinfra":
        return DEEPINFRA_URL, DEEPINFRA_API_KEY
    return VLLM_API_URL.rstrip("/"), VLLM_API_KEY


async def llm_generate(prompt: str, temperature: float = 0.1, max_tokens: int = 512, seed: int | None = 0) -> str:
    try:
        if LLM_PROVIDER in _OPENAI_COMPATIBLE:
            return await _openai_generate(prompt, temperature, max_tokens, seed)
        return await _ollama_generate(prompt, temperature, max_tokens, seed)
    except httpx.ReadTimeout as e:
        raise RuntimeError(f"LLM 응답 시간 초과 ({_TIMEOUT:.0f}초)") from e
    except httpx.ConnectError as e:
        raise RuntimeError(f"LLM 서버 연결 실패 ({LLM_PROVIDER})") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"LLM HTTP 오류 {e.response.status_code}: {e.response.text[:200]}") from e


async def _ollama_generate(prompt: str, temperature: float, max_tokens: int, seed: int | None) -> str:
    options = {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192}
    if seed is not None:
        options["seed"] = seed
    # 응답 지연 방지: Qwen thinking 모드 끔
    payload = {"model": LLM_MODEL, "prompt": prompt, "stream": False, "think": False, "options": options}
    resp = await _shared_client().post(f"{OLLAMA_URL}/api/generate", json=payload)
    resp.raise_for_status()
    return resp.json()["response"].strip()


async def _openai_generate(prompt: str, temperature: float, max_tokens: int, seed: int | None) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if LLM_PROVIDER in {"vllm", "deepinfra"}:
        # 응답 지연 방지: Qwen thinking 모드 끔
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        if seed is not None:
            payload["seed"] = seed
    url, key = _openai_endpoint()
    resp = await _shared_client().post(
        f"{url}/chat/completions", json=payload, headers={"Authorization": f"Bearer {key}"}
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


async def check_llm() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if LLM_PROVIDER in _OPENAI_COMPATIBLE:
                url, key = _openai_endpoint()
                resp = await client.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"})
            else:
                resp = await client.get(f"{OLLAMA_URL}/api/tags")
        return resp.status_code == 200
    except httpx.HTTPError:
        return False
