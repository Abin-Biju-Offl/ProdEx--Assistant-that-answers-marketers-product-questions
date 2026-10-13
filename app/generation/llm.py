"""OpenAI-compatible LLM client (spec section 6).

Plain httpx against /chat/completions, so the same code talks to Ollama, vLLM,
LM Studio or a paid API - the base URL and key come from config.
"""

from __future__ import annotations

import logging
import threading

import httpx

from app.config import Settings, settings
from app.generation.prompts import SUMMARIZE_PROMPT

log = logging.getLogger(__name__)

_lock = threading.Lock()
_instances: dict[tuple[str, str], LLM] = {}


class LLMUnavailable(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: Settings) -> None:
        self.base_url = cfg.llm_base_url.rstrip("/")
        self.model = cfg.llm_model
        self.api_key = cfg.llm_api_key
        self.temperature = cfg.llm_temperature
        self.timeout = cfg.llm_timeout_seconds
        self._client = httpx.Client(timeout=self.timeout)

    @property
    def name(self) -> str:
        return self.model

    def chat(self, messages: list[dict], max_tokens: int = 400) -> str:
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
            )
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"could not reach the LLM at {self.base_url}: {exc}") from exc

        if response.status_code >= 400:
            raise LLMUnavailable(f"LLM returned {response.status_code}: {response.text[:300]}")
        try:
            return response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMUnavailable(f"unexpected LLM response shape: {response.text[:300]}") from exc

    def summarize(self, thread: str, max_tokens: int = 300) -> str:
        return self.chat(
            [{"role": "system", "content": SUMMARIZE_PROMPT.replace("{thread}", thread[:12000])}],
            max_tokens=max_tokens,
        )

    def ping(self) -> bool:
        try:
            self._client.get(f"{self.base_url}/models", timeout=10)
            return True
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


def get_llm(cfg: Settings | None = None) -> LLM:
    cfg = cfg or settings
    key = (cfg.llm_base_url, cfg.llm_model)
    if key not in _instances:
        with _lock:
            _instances.setdefault(key, LLM(cfg))
    return _instances[key]