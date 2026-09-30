"""Свежесть расширения 1С: версия коммита в git vs версия, зашитая в базу.

Поток «git → база»: владелец базы грузит onec/ext/ в конфигуратор и обновляет
БД. Пока перезаливки нет — BSL-фиксы из новых коммитов не действуют, а агент
может молча работать на старом коде (падение тулзы или враньё «Объект не найден»).

Механизм: при каждом изменении onec/ext/ скрипт `scripts/bump_ext_version.py`
пишет хеш последнего коммита, тронувшего папку, в `onec/ext/ExtVersion.txt` и
подставляет его в `ВерсияРасширения()` менеджера обработки
`a1c_ИнструментДерево` (строка `Версия = "<хеш>"`; оба файла коммитятся вместе
с правкой). Тулза `get_extension_version` отдаёт зашитую версию модели.
Сравнение «git vs база» делает бэкенд-тулза `check_extension_freshness` — она же
в промпте агента заставляет модель проверить свежесть перед первым обращением
к данным.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.tools import ToolContext, ToolDefinition
from app.onec.client import OnecClient
from app.onec.direct import JsonRpcOnecClient

log = logging.getLogger("agent1c.ext_version")

#: onec/ext/ExtVersion.txt — лежит рядом с XML расширения.
EXT_VERSION_FILE = Path(__file__).resolve().parents[4] / "onec" / "ext" / "ExtVersion.txt"

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")


def read_git_ext_version(path: Path | str = EXT_VERSION_FILE) -> str:
    """Версия коммита из ExtVersion.txt. Пусто — файл не создан (ещё не бампал)."""
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return raw.splitlines()[0].strip() if raw else ""


def _is_commit(value: str) -> bool:
    return bool(_COMMIT_RE.match(value))


class CheckFreshnessArgs(BaseModel):
    # Пусто — взять base_url из контекста сессии (бэкенд подставляет сам).
    base_url: str = Field(
        default="",
        max_length=256,
        description="Корень публикации базы вида http://host/base; можно опустить — возьмётся из сессии",
    )


def make_ext_freshness_tool(client_factory: Callable[[str], OnecClient] | None = None) -> ToolDefinition:
    """Локальная тулза check_extension_freshness.

    client_factory(root) -> клиент с async call_tool(name, args) — для тестов;
    по умолчанию строит JsonRpcOnecClient под ONEC_USERNAME/ONEC_PASSWORD.
    """
    from app.config import settings  # лениво: не тянуть конфиг в импорте модуля

    def _client(root: str) -> OnecClient:
        if client_factory is not None:
            return client_factory(root)
        return JsonRpcOnecClient(root, username=settings.onec_username, password=settings.onec_password)

    async def handler(args: CheckFreshnessArgs, ctx: ToolContext) -> str:
        root = args.base_url.strip() or ctx.base_url
        if not root:
            return (
                "Неизвестная база: в сессии нет base_url и аргумент не передан. "
                "Укажи base_url (корень публикации вида http://host/base)."
            )
        git_version = read_git_ext_version()
        if not _is_commit(git_version):
            # Бамп ещё не делался — сравнение невозможно, но это не «устарело».
            return (
                "Версия расширения в git не зафиксирована (onec/ext/ExtVersion.txt пуст или бит). "
                "Свежесть проверить нельзя; если расширение менялось — запусти scripts/bump_ext_version.py."
            )
        try:
            result = await _client(root).call_tool("get_extension_version", {})
        except Exception as e:  # noqa: BLE001 — ошибка сети/1С в текст тулзы, не в крах чата
            return (
                f"Не удалось опросить базу {root}: {e}. "
                f"Версия в git: {git_version}. Проверь доступность публикации."
            )
        base_version = str(result).strip() if result is not None else ""
        if not _is_commit(base_version):
            return (
                f"База {root} не вернула версию коммита (получено: {base_version!r}). "
                "Расширение загружено до введения ExtVersion.txt — перезалить из git, чтобы сравнение работало. "
                f"Версия в git: {git_version}."
            )
        if base_version.lower() == git_version.lower():
            return (
                f"Расширение свежее: база {root} работает на коммите {base_version}, "
                f"как и git. Можно отвечать по данным."
            )
        return (
            f"РАСШИРЕНИЕ УСТАРЕЛО: база {root} работает на коммите {base_version}, "
            f"в git уже {git_version}. BSL-фиксы из новых коммитов НЕ действуют. "
            "Скажи пользователю, что нужно перезалить расширение из onec/ext/ (загрузка из файлов + "
            "обновление базы), и не опирайся на поведение инструментов, которое могло измениться."
        )

    return ToolDefinition(
        name="check_extension_freshness",
        description=(
            "Проверить, что расширение 1С в базе свежее (версия коммита совпадает с git). "
            "Вызвать ПЕРЕД первым обращением к данным 1С в диалоге: если база работает на старом "
            "коде расширения — ответы по данным ненадёжны. Аргумент base_url — корень публикации базы."
        ),
        args_model=CheckFreshnessArgs,
        handler=handler,
        server="local",
    )
