"""Эмбеддинги: провайдер выбирается конфигом.

- tei: настоящий TEI-сервис (native /embed API), профиль rag в compose.
- fake: детерминированные вектора для dev/test без GPU и без скачивания
  моделей. Ранжирование идёт по лексическому пересечению (сумма word-seeded
  векторов) — честный plumbing-тест retrieval, не качество поиска.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from typing import Any, Protocol

import httpx

from app.db.models import EMBEDDING_DIM

_WORD = re.compile(r"\w+", re.UNICODE)


class Embeddings(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """По вектору на каждый текст, порядок сохраняется."""
        ...


class TEIEmbeddings:
    """Клиент native API Text Embeddings Inference: POST {base_url}/embed."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            resp = await client.post(f"{self._base_url}/embed", json={"inputs": texts})
            resp.raise_for_status()
            data: Any = resp.json()
        if isinstance(data[0], (int, float)):
            return [list(data)]
        return [list(vec) for vec in data]


class FakeEmbeddings:
    """Детерминированные L2-нормированные вектора: сумма word-seeded гауссиан.

    Тексты с общими словами получают близкие вектора — retrieval на них
    работает как лексический поиск. Детерминировано по (seed, слово).
    """

    def __init__(self, dim: int = EMBEDDING_DIM, seed: int = 7) -> None:
        self._dim = dim
        self._seed = seed

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        words = _WORD.findall(text.lower()) or ["<empty>"]
        for word in words:
            digest = hashlib.sha256(f"{self._seed}:{word}".encode()).digest()
            rng = random.Random(int.from_bytes(digest, "big"))
            for i in range(self._dim):
                vec[i] += rng.gauss(0.0, 1.0)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


def build_embeddings(provider: str, tei_base_url: str) -> Embeddings:
    if provider == "tei":
        return TEIEmbeddings(tei_base_url)
    if provider == "fake":
        return FakeEmbeddings()
    raise ValueError(f"Неизвестный embeddings_provider: {provider!r} (жди 'fake' или 'tei')")
