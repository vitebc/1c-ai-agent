"""Тулзы get_agent / get_skill: чтение файлов AGENT.md и SKILL.md целиком.

`list_registry` отдаёт только метаданные (кто есть, какие `tools`/`mcp`), но не
текст промптов. Для анализа и проверки существующих конфигов skill-writer должен
читать сами файлы: иначе он может знать, что агент существует, но не знать, как он
написан. Эти тулзы закрывают тот пробел.

Безопасность: работаем ТОЛЬКО по имени из уже загруженного реестра
(`AgentRegistry.get` / `SkillRegistry.get`) и читаем файл по `source` этого
объекта. Путь никогда не собирается из пользовательского ввода, а имя
дополнительно проверяется тем же `_NAME_RE`, что и в лоадерах (латиница+дефы),
так что `../../etc/passwd` отсекается до обращения к диску. Универсального
чтения файлов по произвольному пути тут нет — только два конкретных каталога.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.tools import ToolContext, ToolDefinition

#: Потолок на размер ответа: защита от поехавшего контекста, если файл раздуют.
#: Текущие AGENT.md/SKILL.md — 2–13 КБ, так что лимит не режет обычный случай.
MAX_FILE_CHARS = 60_000

#: Имя объекта: латиница/цифры/дефис (тот же формат, что требуют лоадеры).
#: Отсекает ../../, пробелы и прочее до обращения к реестру.
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class _NameArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="Имя агента или скила (как в реестре)")

    @property
    def safe_name(self) -> str:
        return self.name.strip().lower()


def _read_capped(path: str) -> str:
    """Прочитать файл с обрезкой по потолку (маркер усечения виден модели)."""
    text = Path(path).read_text(encoding="utf-8")
    if len(text) <= MAX_FILE_CHARS:
        return text
    return (
        text[:MAX_FILE_CHARS]
        + f"\n\n[ОБРЕЗАНО: файл длиннее {MAX_FILE_CHARS} символов, показана только начальная часть. "
        "Не делай выводов о хвосте файла — скажи пользователю, что нужен полный текст.]"
    )


def _reject_bad_name(name: str, available: list[str], kind: str) -> str | None:
    """Текст ошибки для некорректного/неизвестного имени (None — имя валидно)."""
    listing = ", ".join(available) or "(пусто)"
    if not _NAME_RE.match(name):
        sample = available[0] if available else "my-agent"
        return (
            f"ERROR: недопустимое имя {name!r}. Ожидается латиница/цифры/дефис "
            f"(напр. {sample}). Доступны: {listing}."
        )
    if name not in available:
        return f"ERROR: {kind} {name!r} не найден. Доступны: {listing}. Выбери из них."
    return None


def make_get_agent_tool(
    *,
    agents_dir: str | None = None,
) -> ToolDefinition:
    """Тулза get_agent: сырой AGENT.md целиком (frontmatter + тело промпта)."""
    from app.config import settings  # лениво: не тянем конфиг в импорте модуля

    def _root() -> str:
        return agents_dir if agents_dir is not None else settings.agents_dir

    async def handler(args: _NameArgs, ctx: ToolContext) -> str:  # noqa: ARG001
        from app.agents import AgentRegistry

        reg = AgentRegistry.load(_root())
        name = args.safe_name
        available = reg.names
        bad = _reject_bad_name(name, available, "агент")
        if bad:
            return bad
        agent = reg.get(name)
        if agent is None or not agent.source:
            return f"ERROR: у агента {name!r} нет исходного файла."
        try:
            return _read_capped(agent.source)
        except OSError as e:
            return f"ERROR: не удалось прочитать {agent.source}: {e}"

    return ToolDefinition(
        name="get_agent",
        description=(
            "Прочитать файл агента AGENT.md целиком: frontmatter (name, title, tools, skills, mcp) "
            "и текст системного промпта. Вызывай перед анализом, правкой или ревью чужого AGENT.md — "
            "не полагайся на память. Имя бери из list_registry({'kind':'agents'})."
        ),
        args_model=_NameArgs,
        handler=handler,
        server="local",
    )


def make_get_skill_tool(
    *,
    skills_dir: str | None = None,
) -> ToolDefinition:
    """Тулза get_skill: сырой SKILL.md целиком (frontmatter + тело промпта)."""
    from app.config import settings  # лениво: не тянем конфиг в импорте модуля

    def _root() -> str:
        return skills_dir if skills_dir is not None else settings.skills_dir

    async def handler(args: _NameArgs, ctx: ToolContext) -> str:  # noqa: ARG001
        from app.skills import SkillRegistry

        reg = SkillRegistry.load(_root())
        name = args.safe_name
        available = reg.names
        bad = _reject_bad_name(name, available, "скил")
        if bad:
            return bad
        skill = reg.get(name)
        if skill is None or not skill.source:
            return f"ERROR: у скила {name!r} нет исходного файла."
        try:
            return _read_capped(skill.source)
        except OSError as e:
            return f"ERROR: не удалось прочитать {skill.source}: {e}"

    return ToolDefinition(
        name="get_skill",
        description=(
            "Прочитать файл скила SKILL.md целиком: frontmatter (name, description, tools) "
            "и текст промпта. Вызывай перед анализом, правкой или ревью существующего скила "
            "и чтобы взять его как образец стиля. Имя бери из list_registry({'kind':'skills'})."
        ),
        args_model=_NameArgs,
        handler=handler,
        server="local",
    )
