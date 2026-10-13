"""Cross-encoder reranker interface (spec section 6)."""

from __future__ import annotations

import logging
import math
import threading
from typing import Protocol

from app.config import Settings, settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_instances: dict[str, Reranker] = {}


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, passages: list[str]) -> list[tuple[int, float]]:
        """Return [(passage_index, score)] sorted best first, score in 0..1."""
        ...


class LocalReranker:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model = CrossEncoder(model_name)

    @property
    def name(self) -> str:
        return f"local:{self.model_name}"

    def rerank(self, query: str, passages: list[str]) -> list[tuple[int, float]]:
        if not passages:
            return []
        logits = self._model.predict([(query, p) for p in passages])
        # CrossEncoder outputs a raw relevance logit; squash it into 0..1 so that
        # MIN_RERANK_SCORE is a probability-like threshold.
        scores = [1.0 / (1.0 + math.exp(-float(s))) for s in logits]
        return sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)


class NullReranker:
    """Explicit opt-out: keeps hybrid order and reports 1.0. Not the default."""

    name = "none"

    def rerank(self, query: str, passages: list[str]) -> list[tuple[int, float]]:
        return [(i, 1.0) for i in range(len(passages))]


def get_reranker(cfg: Settings | None = None) -> Reranker:
    cfg = cfg or settings
    key = f"{cfg.rerank_provider}:{cfg.rerank_model}"
    if key in _instances:
        return _instances[key]
    with _lock:
        if key in _instances:
            return _instances[key]
        reranker: Reranker = (
            NullReranker() if cfg.rerank_provider == "none" else LocalReranker(cfg.rerank_model)
        )
        _instances[key] = reranker
        return reranker