"""Горячая мапа база -> разрешённые search-серверы агрегатора.

Определяет, какие кодовые индексы (search-ka-update / search-ka-rs / ...)
видит агент для конкретной базы: вопрос из базы X ищет код в индексе X,
а не во всех сразу. Формат файла (SEARCH_MAPS_FILE, по умолчанию
backend/search-maps.conf): "имя_базы=сервер1,сервер2;..." — имя НРег,
серверы через запятую. База без записи в мапе -> все search-серверы
(без фильтрации). Кривая запись не роняет бэкенд: warning + предыдущее
хорошее значение (тот же паттерн, что bases.py).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger("agent1c.search_maps")


def _default_search_maps_file() -> str:
    # src/app/onec/search_maps.py -> backend/search-maps.conf (тот же путь, что bases.conf).
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "search-maps.conf")
    )


def search_maps_file() -> str:
    """Путь к файлу мапы (SEARCH_MAPS_FILE). Пусто — дефолтный backend/search-maps.conf."""
    return os.environ.get("SEARCH_MAPS_FILE", "").strip() or _default_search_maps_file()


@dataclass
class _State:
    mtime: float = -1.0
    at: float = 0.0
    map: dict[str, list[str]] | None = field(default=None)


_state = _State()
_TTL_S = 2.0


def parse_search_maps(raw: str) -> dict[str, list[str]]:
    """'doc=search-ka-update,search-ka-rs;ca2_td=search-ka-td' -> {имя: [серверы]}.

    Пустые записи и комментарии (#) пропускаются. Кривая запись (без =) — ValueError.
    """
    out: dict[str, list[str]] = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#"):
            continue
        if "=" not in chunk:
            raise ValueError(f"запись без '=': {chunk!r}")
        name, _, servers = chunk.partition("=")
        name = name.strip().lower()
        server_list = [s.strip() for s in servers.split(",") if s.strip()]
        if not name or not server_list:
            raise ValueError(f"пустое имя или список серверов: {chunk!r}")
        out[name] = server_list
    return out


def get_search_maps() -> dict[str, list[str]]:
    """Текущая мапа база -> search-серверы (hot-reload по mtime, TTL 2с)."""
    path = search_maps_file()
    now = time.monotonic()
    # map is None (холодный старт или явный сброс) — читаем сразу, не ждём TTL.
    if path and (_state.map is None or now - _state.at >= _TTL_S):
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
                    new_map = parse_search_maps(raw)
                    _state.map = new_map
                    _state.mtime = mtime
                    log.info("мапа search-серверов перечитана из %s: %d баз", path, len(new_map))
                except (OSError, ValueError) as e:
                    log.warning("не удалось перечитать мапу search-серверов из %s: %s", path, e)
    return dict(_state.map or {})


def allowed_search_servers(base_name: str | None) -> list[str] | None:
    """Разрешённые search-серверы для базы.

    None — фильтрация не нужна (базы нет или её нет в мапе): все серверы,
    разрешённые агентом в AGENT.md. Пустой список — база есть, но серверов
    ей не назначено: кодовые тулзы реестру не выдаются вовсе.
    """
    if not base_name:
        return None
    maps = get_search_maps()
    key = base_name.strip().lower()
    if key in maps:
        return list(maps[key])
    return None
