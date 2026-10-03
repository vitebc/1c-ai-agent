"""Per-user креды 1С: мапа login → password из файла (hot-reload).

Формат файла (ONEC_CREDS_FILE, дефолт backend/creds.conf):
    "ivanov=pass1;petrov=pass2;..."

Тот же механизм mtime/TTL, что в bases.py. Кривая запись не роняет бэкенд —
warning + предыдущее хорошее значение. Fallback — ONEC_CREDENTIALS из .env.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger("agent1c.creds")


def _env_creds_map() -> dict[str, str]:
    """Fallback-мапа из .env (ONEC_CREDENTIALS). Ленивый импорт против цикла."""
    from app.config import settings

    return _parse_raw(settings.onec_credentials)


_TTL_S = 2.0


@dataclass
class _State:
    mtime: float = -1.0
    at: float = 0.0
    map: dict[str, str] | None = field(default=None)


_state = _State()


def creds_file() -> str:
    """Путь к файлу кредов (ONEC_CREDS_FILE). Пусто — только .env."""
    return os.environ.get("ONEC_CREDS_FILE", "").strip() or _default_creds_file()


def _default_creds_file() -> str:
    # src/app/onec/creds.py -> backend/creds.conf (в контейнере /app/creds.conf).
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "creds.conf"))


def _parse_raw(raw: str) -> dict[str, str]:
    """Разобрать 'login=pass;...' → {login: pass}. Пусто — {}."""
    result: dict[str, str] = {}
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"кривая запись в мапе кредов: {entry!r}")
        login, _, password = entry.partition("=")
        login = login.strip().lower()
        password = password.strip()
        if not login or not password:
            raise ValueError(f"пустой login или password: {entry!r}")
        result[login] = password
    return result


def get_creds_map() -> dict[str, str]:
    """Текущая мапа кредов: файл (hot) → fallback на .env."""
    path = creds_file()
    now = time.monotonic()
    if path and now - _state.at >= _TTL_S:
        _state.at = now
        try:
            st = os.stat(path)
        except OSError:
            st = None
        if st is not None:
            mtime = st.st_mtime
            if mtime != _state.mtime or _state.map is None:
                try:
                    with open(path, encoding="utf-8") as f:
                        raw = f.read()
                    new_map = _parse_raw(raw)
                    _state.map = new_map
                    _state.mtime = mtime
                    log.info("мапа кредов перечитана из %s: %d пользователей", path, len(new_map))
                except (OSError, ValueError) as e:
                    log.warning("не удалось перечитать мапу кредов из %s: %s", path, e)
    if _state.map is not None:
        return dict(_state.map)
    return _env_creds_map()


def get_user_password(login: str) -> str | None:
    """Пароль пользователя 1С. None — кредов нет."""
    login = (login or "").strip().lower()
    if not login:
        return None
    return get_creds_map().get(login)
