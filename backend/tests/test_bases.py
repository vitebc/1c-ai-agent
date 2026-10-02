"""Горячая мапа баз (app.onec.bases): файл -> hot-reload без рестарта бэкенда."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.onec import bases as bases_mod


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Каждый тест — с чистым кэшем и без файла по умолчанию."""

    def _reset() -> None:
        bases_mod._state.mtime = -1.0
        bases_mod._state.at = 0.0
        bases_mod._state.map = None

    _reset()
    monkeypatch.setattr(bases_mod, "_TTL_S", 2.0)
    # Файл по умолчанию не должен существовать в песочнице: переопределяем путь.
    monkeypatch.setenv("ONEC_BASES_FILE", str(tmp_path / "bases.conf"))
    yield
    _reset()


def test_fallback_to_env_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """Файла нет — мапа из settings (ONEC_BASES из .env)."""
    monkeypatch.setattr(bases_mod, "_env_base_map", lambda: {"ca2": "http://h/ca2"})
    assert bases_mod.get_bases_map() == {"ca2": "http://h/ca2"}


def test_file_overrides_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "bases.conf"
    f.write_text("doc3_test=http://192.168.0.69:81/doc3_test", encoding="utf-8")
    monkeypatch.setattr(bases_mod, "_env_base_map", lambda: {"ca2": "http://h/ca2"})
    assert bases_mod.get_bases_map() == {"doc3_test": "http://192.168.0.69:81/doc3_test"}


def test_hot_reload_on_mtime_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Правка файла (mtime сменился) подхватывается без рестарта."""
    f = tmp_path / "bases.conf"
    f.write_text("a=http://h/a", encoding="utf-8")
    assert bases_mod.get_bases_map() == {"a": "http://h/a"}

    # Новая запись + сдвигаем mtime в будущее (гарантированно != кэшированный).
    f.write_text("a=http://h/a;b=http://h/b", encoding="utf-8")
    future = time.time() + 10
    os.utime(f, (future, future))
    # TTL: принудительно «истёк» — следующий вызов перечитает.
    bases_mod._state.at = time.monotonic() - bases_mod._TTL_S - 1
    assert bases_mod.get_bases_map() == {"a": "http://h/a", "b": "http://h/b"}


def test_ttl_suppresses_reread(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """В пределах TTL файл не перечитывается (кэш)."""
    f = tmp_path / "bases.conf"
    f.write_text("a=http://h/a", encoding="utf-8")
    assert bases_mod.get_bases_map() == {"a": "http://h/a"}

    # Изменили содержимое, но mtime не сдвинули и TTL не истёк — кэш.
    f.write_text("a=http://h/a;b=http://h/b", encoding="utf-8")
    os.utime(f, (time.time() - 100, time.time() - 100))  # старый mtime
    assert bases_mod.get_bases_map() == {"a": "http://h/a"}


def test_bad_file_falls_back_to_last_good(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Кривая запись в файле не роняет бэкенд: работаем с последним хорошим."""
    f = tmp_path / "bases.conf"
    f.write_text("a=http://h/a", encoding="utf-8")
    assert bases_mod.get_bases_map() == {"a": "http://h/a"}

    f.write_text("noequals", encoding="utf-8")
    future = time.time() + 10
    os.utime(f, (future, future))
    bases_mod._state.at = time.monotonic() - bases_mod._TTL_S - 1
    # Кривой парсинг -> warning, кэш остаётся с предыдущим значением.
    assert bases_mod.get_bases_map() == {"a": "http://h/a"}


def test_bad_file_falls_back_to_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Кривой файл при пустом кэше -> fallback на .env."""
    f = tmp_path / "bases.conf"
    f.write_text("noequals", encoding="utf-8")
    monkeypatch.setattr(bases_mod, "_env_base_map", lambda: {"ca2": "http://h/ca2"})
    assert bases_mod.get_bases_map() == {"ca2": "http://h/ca2"}


def test_resolve_uses_hot_map(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """resolve_base_root берёт мапу из hot-модуля, а не из settings."""
    from app.api.chat import resolve_base_root

    f = tmp_path / "bases.conf"
    f.write_text("hot=http://10.0.0.5/hot", encoding="utf-8")
    # В .env этой базы нет — только в файле.
    monkeypatch.setattr(bases_mod, "_env_base_map", lambda: {})
    assert resolve_base_root("hot", None) == "http://10.0.0.5/hot"
