"""Рантайм-скилы чат-агента: SKILL.md-файлы → фильтр инструментов + промпт.

Формат описан в `backend/skills/SKILL.md`. Битый файл чат не роняет —
скил пропускается, причина видна в `SkillRegistry.errors` и `GET /skills`.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.frontmatter import FrontmatterError, parse_frontmatter
from app.rag.embeddings import Embeddings

log = logging.getLogger("agent1c.skills")

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class SkillFormatError(ValueError):
    """SKILL.md не соответствует формату из backend/skills/SKILL.md."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    tools: tuple[str, ...]
    prompt: str
    source: str = ""  # путь к SKILL.md, для отладки

    @property
    def system_block(self) -> str:
        """Дополнение к базовому системному промпту."""
        return f"# Скилл: {self.name}\n{self.prompt}".rstrip()


def parse_skill_file(path: Path) -> Skill:
    """Прочитать и провалидировать один SKILL.md. Ошибки — SkillFormatError."""
    try:
        meta, prompt = parse_frontmatter(path)
    except FrontmatterError as e:
        raise SkillFormatError(str(e)) from e

    name = meta.get("name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SkillFormatError(f"{path}: нужен name латиницей через дефис, получено {name!r}")
    if name != path.parent.name:
        raise SkillFormatError(f"{path}: name {name!r} не совпадает с именем папки {path.parent.name!r}")
    description = meta.get("description", "")
    if not isinstance(description, str) or not description.strip():
        raise SkillFormatError(f"{path}: нужен непустой description")
    tools = meta.get("tools")
    if not isinstance(tools, list) or not tools or any(not isinstance(t, str) or not t for t in tools):
        raise SkillFormatError(f"{path}: нужен непустой список tools: [a, b]")
    return Skill(name=name, description=description.strip(), tools=tuple(tools), prompt=prompt, source=str(path))


@dataclass
class SkillRegistry:
    skills: list[Skill] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, skills_dir: Path | str) -> SkillRegistry:
        """Сканировать skills_dir/*/SKILL.md. Битые — пропуск с записью в errors."""
        reg = cls()
        root = Path(skills_dir)
        if not root.is_dir():
            return reg
        for path in sorted(root.glob("*/SKILL.md")):
            try:
                reg.skills.append(parse_skill_file(path))
            except SkillFormatError as e:
                log.warning("скип скила: %s", e)
                reg.errors.append(str(e))
        return reg

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.skills if s.name == name), None)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.skills]

    async def match(self, query: str, embeddings: Embeddings, *, min_score: float = 0.0) -> Skill | None:
        """Top-1 по косинусной близости запроса к description. Пусто/ниже порога — None."""
        if not self.skills or not query.strip():
            return None
        vecs = await embeddings.embed([query, *(s.description for s in self.skills)])
        if len(vecs) != len(self.skills) + 1:
            return None
        query_vec = _normalized(vecs[0])
        best: Skill | None = None
        best_score = min_score
        for skill, vec in zip(self.skills, vecs[1:], strict=True):
            score = sum(a * b for a, b in zip(query_vec, _normalized(vec), strict=False))
            if score > best_score:
                best, best_score = skill, score
        return best


def _normalized(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]
