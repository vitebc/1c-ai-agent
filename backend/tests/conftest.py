"""Общее для тестов: движок БД с пулом соединений, привязанным к event loop.

Каждый asyncio.run() / портал TestClient — новый loop, а pooled-коннекты
привязаны к старому. Поэтому перед каждым тестом пул сбрасываем; внутри теста —
один loop на все обращения к БД (или явный dispose перед сменой loop).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from app.db.session import engine


@pytest.fixture(autouse=True)
def _fresh_engine_pool() -> Iterator[None]:
    asyncio.run(engine.dispose())
    yield


@pytest.fixture(autouse=True)
def _clean_dependency_overrides() -> Iterator[None]:
    yield
    from app.main import app

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_jwt_in_tests(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Тесты не ходят в 1С под JWT: обнуляем секрет (dev-режим Basic auth).

    В .env разработчика JWT_SECRET задан (per-user RLS), и без токена /chat
    отвечает 401 — тесты, написанные до per-user RLS, этого не знают.
    Тесты самого JWT (test_jwt.py) секрет не трогают — он им нужен.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret", "")
    yield
