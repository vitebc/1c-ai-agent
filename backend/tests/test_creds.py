"""Per-user креды 1С (app.onec.creds): hot-reload, fallback, кривой файл."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.onec import creds as creds_mod


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    def _reset() -> None:
        creds_mod._state.mtime = -1.0
        creds_mod._state.at = 0.0
        creds_mod._state.map = None

    _reset()
    monkeypatch.setattr(creds_mod, "_TTL_S", 2.0)
    monkeypatch.setenv("ONEC_CREDS_FILE", str(tmp_path / "creds.conf"))
    yield
    _reset()


def test_fallback_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Файла нет — мапа из settings (ONEC_CREDENTIALS)."""
    monkeypatch.setattr(creds_mod, "_env_creds_map", lambda: {"ivanov": "pass1"})
    assert creds_mod.get_user_password("ivanov") == "pass1"
    assert creds_mod.get_user_password("unknown") is None


def test_file_overrides_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "creds.conf"
    f.write_text("ivanov=pass1;petrov=pass2", encoding="utf-8")
    monkeypatch.setattr(creds_mod, "_env_creds_map", lambda: {"ivanov": "env_pass"})
    assert creds_mod.get_user_password("ivanov") == "pass1"
    assert creds_mod.get_user_password("petrov") == "pass2"


def test_hot_reload_on_mtime_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "creds.conf"
    f.write_text("a=p1", encoding="utf-8")
    assert creds_mod.get_user_password("a") == "p1"

    f.write_text("a=p1;b=p2", encoding="utf-8")
    future = time.time() + 10
    os.utime(f, (future, future))
    creds_mod._state.at = time.monotonic() - creds_mod._TTL_S - 1
    assert creds_mod.get_user_password("b") == "p2"


def test_bad_file_falls_back_to_last_good(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "creds.conf"
    f.write_text("a=p1", encoding="utf-8")
    assert creds_mod.get_user_password("a") == "p1"

    f.write_text("noequals", encoding="utf-8")
    future = time.time() + 10
    os.utime(f, (future, future))
    creds_mod._state.at = time.monotonic() - creds_mod._TTL_S - 1
    # Кривой парсинг → warning, кэш остаётся.
    assert creds_mod.get_user_password("a") == "p1"


def test_login_case_insensitive(tmp_path: Path) -> None:
    f = tmp_path / "creds.conf"
    f.write_text("Ivanov=pass1", encoding="utf-8")
    assert creds_mod.get_user_password("ivanov") == "pass1"
    assert creds_mod.get_user_password("IVANOV") == "pass1"


def test_empty_login_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "creds.conf"
    f.write_text("a=p1", encoding="utf-8")
    assert creds_mod.get_user_password("") is None
    assert creds_mod.get_user_password("   ") is None
