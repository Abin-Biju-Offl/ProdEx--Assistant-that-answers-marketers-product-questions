"""Embedding provider interface (spec section 6).

`local` runs a sentence-transformers model in-process: free, offline, no content
leaves the machine. Anything else is refused unless ALLOW_EXTERNAL_PROVIDERS=true.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from app.config import Settings, settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_instances: dict[str, Embedder] = {}

# bge models expect this instruction on the query side only.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    def __init__(self, model_name: str, dim: int) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.dim = dim
        self._model = SentenceTransformer(model_name)

    @property
    def name(self) -> str:
        return f"local:{self.model_name}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        if "bge" in self.model_name.lower():
            text = _BGE_QUERY_PREFIX + text
        return self.embed_documents([text])[0]


class OpenAICompatibleEmbedder:
    """Any OpenAI-compatible /embeddings endpoint.

    Covers OpenAI, Azure OpenAI, Voyage, NVIDIA NIM and local vLLM/LM Studio.
    Refused unless ALLOW_EXTERNAL_PROVIDERS=true and the host is not local
    (spec section 14.8).
    """

    name = "openai_compatible"

    def __init__(self, cfg: Settings) -> None:
        cfg.require_local_only("EMBED_BASE_URL", cfg.embed_base_url)
        self.model = cfg.embed_model
        self.base_url = cfg.embed_base_url.rstrip("/")
        self.api_key = cfg.embed_api_key
        self.dim = cfg.embed_dim
        self._client = None

    def _post(self, texts: list[str]) -> list[list[float]]:
        import httpx

        if self._client is None:
            self._client = httpx.Client(timeout=60)
        r = self._client.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
        )
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._post(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._post([text])[0]


def get_embedder(cfg: Settings | None = None) -> Embedder:
    cfg = cfg or settings
    key = f"{cfg.embed_provider}:{cfg.embed_model}:{cfg.embed_base_url}"
    if key in _instances:
        return _instances[key]
    with _lock:
        if key in _instances:
            return _instances[key]
        if cfg.embed_provider == "local":
            embedder: Embedder = LocalEmbedder(cfg.embed_model, cfg.embed_dim)
        elif cfg.embed_provider == "openai_compatible":
            embedder = OpenAICompatibleEmbedder(cfg)
        else:  # pragma: no cover - pydantic restricts the choices
            raise ValueError(f"unknown EMBED_PROVIDER {cfg.embed_provider!r}")
        _instances[key] = embedder
        return embedder


def embed_text_vector(embedding: list[float]) -> str:
    """pgvector accepts a bracketed string literal."""
    return "[" + ",".join(f"{v:.7f}" for v in embedding) + "]"