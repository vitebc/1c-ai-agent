"""Общий плоский frontmatter-парсер для SKILL.md и AGENT.md.

Только плоский поднабор: `ключ: значение`, значения — строка (опционально
в кавычках) или список `[a, b]` (элементы опционально в кавычках).
Комментарии `#...` и пустые строки пропускаются.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class FrontmatterError(ValueError):
    """Файл не соответствует плоскому формату frontmatter."""


def _parse_value(raw: str, source: str, key: str) -> Any:
    raw = raw.strip()
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise FrontmatterError(f"{source}: ключ {key!r} — список не закрыт ']'")
        return [p.strip().strip("'\"") for p in raw[1:-1].split(",") if p.strip().strip("'\"")]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Прочитать файл, вернуть (meta, тело после второго '---'). Ошибки — FrontmatterError."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise FrontmatterError(f"{path}: не читается: {e}") from e
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError(f"{path}: файл обязан начинаться с '---'")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise FrontmatterError(f"{path}: нет закрывающего '---' frontmatter") from None
    meta: dict[str, Any] = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if ":" not in raw:
            raise FrontmatterError(f"{path}: строка frontmatter без ':': {raw.strip()!r}")
        key, _, value = raw.partition(":")
        meta[key.strip()] = _parse_value(value, str(path), key.strip())
    return meta, "\n".join(lines[end + 1 :]).strip()
