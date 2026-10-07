"""Паттерны чат-агента: <name>.md-файлы → ленивая подгрузка через get_pattern.

Формат описан в `backend/patterns/README.md`. Битый файл чат не роняет —
паттерн пропускается, причина видна в `PatternRegistry.errors`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.tools import ToolDefinition
from app.frontmatter import FrontmatterError, parse_frontmatter

log = logging.getLogger("agent1c.patterns")

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class PatternFormatError(ValueError):
    """Паттерн не соответствует формату из backend/patterns/README.md."""


@dataclass(frozen=True)
class Pattern:
    name: str
    description: str
    text: str
    source: str = ""  # путь к файлу, для отладки
    enabled: bool = True  # enabled: false в frontmatter — скрыт от агента


def _parse_enabled(value: object) -> bool:
    """enabled из frontmatter: булево или строка 'true'/'false'. Нет ключа — True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return True


def parse_pattern_file(path: Path) -> Pattern:
    """Прочитать и провалидировать один <name>.md. Ошибки — PatternFormatError."""
    try:
        meta, text = parse_frontmatter(path)
    except FrontmatterError as e:
        raise PatternFormatError(str(e)) from e
    name = meta.get("name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise PatternFormatError(f"{path}: нужен name латиницей через дефис, получено {name!r}")
    if name != path.stem:
        raise PatternFormatError(f"{path}: name {name!r} не совпадает с именем файла {path.stem!r}")
    description = meta.get("description", "")
    if not isinstance(description, str) or not description.strip():
        raise PatternFormatError(f"{path}: нужен непустой description")
    if not text:
        raise PatternFormatError(f"{path}: пустое тело паттерна")
    return Pattern(
        name=name,
        description=description.strip(),
        text=text,
        source=str(path),
        enabled=_parse_enabled(meta.get("enabled", True)),
    )


@dataclass
class PatternRegistry:
    patterns: list[Pattern] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, patterns_dir: Path | str) -> PatternRegistry:
        """Сканировать patterns_dir/*.md (кроме README). Битые — пропуск с записью в errors."""
        reg = cls()
        root = Path(patterns_dir)
        if not root.is_dir():
            return reg
        for path in sorted(root.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            try:
                reg.patterns.append(parse_pattern_file(path))
            except PatternFormatError as e:
                log.warning("скип паттерна: %s", e)
                reg.errors.append(str(e))
        return reg

    def get(self, name: str) -> Pattern | None:
        if not _NAME_RE.match(name):
            return None
        return next((p for p in self.patterns if p.name == name), None)

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.patterns]


class PatternArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="Имя паттерна из списка доступных")


def make_pattern_tool(patterns_dir: Path | str) -> ToolDefinition | None:
    """Тулза get_pattern поверх папки паттернов. Пустая папка — None (не регистрируем).

    Агент видит только ВКЛЮЧЁННЫЕ паттерны (enabled != false в frontmatter):
    они перечислены в описании тулзы, выключенные возвращают ERROR."""
    reg = PatternRegistry.load(patterns_dir)
    if not reg.patterns:
        return None
    enabled = [p for p in reg.patterns if p.enabled]
    if not enabled:
        # Все выключены — тулзу не регистрируем (агенту нечего подгружать).
        return None
    available = ", ".join(f"{p.name} ({p.description})" for p in enabled)

    async def handler(args: PatternArgs, ctx: object) -> str:  # noqa: ARG001 — контекст не нужен
        pattern = reg.get(args.name.strip())
        if pattern is None:
            return f"ERROR: неизвестный паттерн {args.name!r}. Доступны: {[p.name for p in enabled]}. Выбери из них."
        if not pattern.enabled:
            return f"ERROR: паттерн {pattern.name!r} отключён. Доступны: {[p.name for p in enabled]}. Выбери из них."
        return pattern.text

    return ToolDefinition(
        name="get_pattern",
        description=(
            "Ленивая подгрузка текстового паттерна (правила, шаблоны) из папки patterns. "
            "Перед ПЕРВЫМ execute_select в диалоге вызови get_pattern и строго следуй тексту. "
            f"Доступны: {available}."
        ),
        args_model=PatternArgs,
        handler=handler,
        server="local",
    )
