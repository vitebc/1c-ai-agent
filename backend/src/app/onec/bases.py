"""Горячая мапа баз ONEC_BASES: файл перечитывается без перезапуска бэкенда.

Источник правды — текстовый файл (ONEC_BASES_FILE, по умолчанию backend/bases.conf),
формат тот же, что в .env: "имя=url;...". Бэкенд сравнивает mtime файла и
перепарсит его при изменении (кэш TTL 2 сек): правка файла на хосте подхватывается
в течение ≤2 сек без рестарта контейнера.

Приоритет: файл (если существует и не пуст) → ONEC_BASES из .env (стартовое
значение, валидируется при старте). Кривая запись в файле НЕ роняет бэкенд —
лог warning и fallback на предыдущее хорошее значение (в отличие от .env, где
кривой конфиг должен ронять старт: там его правят осознанно, а файл — оперативный).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from app.onec.direct import parse_bases_map

log = logging.getLogger("agent1c.bases")


def _env_base_map() -> dict[str, str]:
    """Fallback-мапа из .env. Ленивый импорт: config импортирует onec.direct,
    а onec/__init__ — этот модуль; прямой import settings на верхнем уровне
    даёт циклический импорт при старте."""
    from app.config import settings

    return settings.onec_base_map


#: Минимальный интервал между чтениями файла, сек. Мелкий файл — mtime+read дёшевы,
#: но не на каждый запрос: кэш гасит повторные обращения в пределах окна.
_TTL_S = 2.0


@dataclass
class _State:
    """Кэш hot-мапы: mtime последнего прочтения + время последнего опроса."""

    mtime: float = -1.0
    at: float = 0.0
    map: dict[str, str] | None = field(default=None)


_state = _State()


def bases_file() -> str:
    """Путь к файлу мапы баз (ONEC_BASES_FILE). Пусто — только .env."""
    return os.environ.get("ONEC_BASES_FILE", "").strip() or _default_bases_file()


def _default_bases_file() -> str:
    # src/app/onec/bases.py -> backend/bases.conf. В контейнере /app/src/app/onec/...
    # -> /app/bases.conf (volume из docker-compose.yml).
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "bases.conf"))


def get_bases_map() -> dict[str, str]:
    """Текущая мапа баз: файл (hot) → fallback на settings.onec_base_map."""
    path = bases_file()
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
                    new_map = parse_bases_map(raw)
                    _state.map = new_map
                    _state.mtime = mtime
                    log.info("мапа баз перечитана из %s: %d баз", path, len(new_map))
                except (OSError, ValueError) as e:
                    # Кривая запись в оперативном файле не роняет бэкенд:
                    # работаем с предыдущим хорошим значением, ошибку — в лог.
                    log.warning("не удалось перечитать мапу баз из %s: %s", path, e)
    if _state.map is not None:
        return dict(_state.map)
    return _env_base_map()
