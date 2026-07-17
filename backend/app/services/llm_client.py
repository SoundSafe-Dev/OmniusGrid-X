"""
LLM Client - the swappable inference seam.

This is the *most* modular boundary in the RAG pipeline. It speaks the
OpenAI-compatible ``/v1/chat/completions`` contract, so ANY server that exposes
it can be swapped in by configuration alone - no application code change:

    - vLLM serving a custom-built / fine-tuned Gemma
    - Ollama running a local Gemma
    - Text Generation Inference (TGI)
    - a hosted OpenAI-compatible API

To swap a custom Gemma in, change ``LLM_BASE_URL`` + ``LLM_MODEL`` (+ optional
``LLM_API_KEY``). Because the model is chosen by the *server*, the backend never
imports torch/transformers and never pins to a specific Gemma build.

Supports both a full-response ``generate()`` and a token-streaming
``stream_generate()``. Remote-first (bearer auth, TLS via https URL) and
gracefully unavailable when ``LLM_BASE_URL`` is unset (retrieval-only
deployments keep working).
"""

from typing import List, Dict, Any, Optional, AsyncIterator
from functools import lru_cache
import json

import httpx
import structlog
from pydantic import BaseModel

from app.core.config import settings

logger = structlog.get_logger()


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMClient:
    """OpenAI-compatible chat client for the generation step."""

    def __init__(self) -> None:
        self.base_url: str = settings.LLM_BASE_URL.rstrip("/")
        self.model: str = settings.LLM_MODEL
        self.api_key: str = settings.LLM_API_KEY
        self.timeout: float = settings.LLM_TIMEOUT
        self.default_max_tokens: int = settings.LLM_MAX_TOKENS
        self.default_temperature: float = settings.LLM_TEMPERATURE

    @property
    def available(self) -> bool:
        """True if an LLM endpoint is configured for this deployment."""
        return bool(self.base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_messages(
        self,
        prompt: Optional[str],
        messages: Optional[List[Dict[str, str]]],
        system: Optional[str],
    ) -> List[Dict[str, str]]:
        if messages is not None:
            return messages
        built: List[Dict[str, str]] = []
        if system:
            built.append({"role": "system", "content": system})
        if prompt is not None:
            built.append({"role": "user", "content": prompt})
        return built

    def _payload(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int],
        temperature: Optional[float],
        stream: bool,
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "stream": stream,
        }
        payload.update(extra)  # passthrough for top_p, stop, etc.
        return payload

    def _require_available(self) -> None:
        if not self.available:
            raise RuntimeError(
                "LLM service not configured (LLM_BASE_URL is empty)."
            )

    async def generate(
        self,
        prompt: Optional[str] = None,
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **extra: Any,
    ) -> str:
        """Generate a full completion and return the assistant text.

        Pass either ``prompt`` (+ optional ``system``) or a full ``messages``
        list. Extra OpenAI params (top_p, stop, ...) pass straight through.
        """
        self._require_available()
        built = self._build_messages(prompt, messages, system)
        payload = self._payload(built, max_tokens, temperature, False, extra)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream_generate(
        self,
        prompt: Optional[str] = None,
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **extra: Any,
    ) -> AsyncIterator[str]:
        """Stream the completion, yielding content deltas as they arrive."""
        self._require_available()
        built = self._build_messages(prompt, messages, system)
        payload = self._payload(built, max_tokens, temperature, True, extra)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

    async def health_check(self) -> Dict[str, Any]:
        """Probe the LLM endpoint (lists models on OpenAI-compatible servers)."""
        if not self.available:
            return {"available": False, "reason": "LLM_BASE_URL not set"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
                resp.raise_for_status()
            return {
                "available": True,
                "endpoint": self.base_url,
                "model": self.model,
            }
        except Exception as exc:  # unhealthy, but never crash the probe
            logger.warning("llm_client.health_failed", error=str(exc))
            return {"available": False, "reason": str(exc)}


@lru_cache()
def get_llm_client() -> LLMClient:
    """Cached singleton accessor, mirroring ``get_settings()``."""
    return LLMClient()
