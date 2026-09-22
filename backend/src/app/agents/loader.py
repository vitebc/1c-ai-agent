"""Рантайм-агенты чат-агента: AGENT.md-файлы → системный промпт + фильтры.

Формат описан в `backend/agents/AGENT.md`. Битый файл чат не роняет —
агент пропускается, причина видна в `AgentRegistry.errors` и `GET /agents`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.frontmatter import FrontmatterError, parse_frontmatter

log = logging.getLogger("agent1c.agents")

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: Маркер «все скилы агента» в поле skills.
ALL_SKILLS = "*"


class AgentFormatError(ValueError):
    """AGENT.md не соответствует формату из backend/agents/AGENT.md."""


@dataclass(frozen=True)
class Agent:
    name: str
    title: str
    description: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]  # ("*",) = все скилы
    mcp: str = "default"  # резерв фазы-1: один MCP-сервер
    model: str = ""  # опциональный оверрайд settings.llm_model; пусто = из конфига
    max_rounds: int | None = None  # опциональный оверрайд settings.agent_max_rounds
    prompt: str = ""
    source: str = ""  # путь к AGENT.md, для отладки

    @property
    def allows_all_skills(self) -> bool:
        return ALL_SKILLS in self.skills

    def allows_skill(self, skill_name: str) -> bool:
        """Доступен ли скил внутри агента."""
        return self.allows_all_skills or skill_name in self.skills


def parse_agent_file(path: Path) -> Agent:
    """Прочитать и провалидировать один AGENT.md. Ошибки — AgentFormatError."""
    try:
        meta, prompt = parse_frontmatter(path)
    except FrontmatterError as e:
        raise AgentFormatError(str(e)) from e

    name = meta.get("name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise AgentFormatError(f"{path}: нужен name латиницей через дефис, получено {name!r}")
    if name != path.parent.name:
        raise AgentFormatError(f"{path}: name {name!r} не совпадает с именем папки {path.parent.name!r}")
    title = meta.get("title", "")
    if not isinstance(title, str) or not title.strip():
        raise AgentFormatError(f"{path}: нужен непустой title")
    description = meta.get("description", "")
    if not isinstance(description, str) or not description.strip():
        raise AgentFormatError(f"{path}: нужен непустой description")
    tools = meta.get("tools")
    if not isinstance(tools, list) or not tools or any(not isinstance(t, str) or not t for t in tools):
        raise AgentFormatError(f"{path}: нужен непустой список tools: [a, b]")
    skills = meta.get("skills")
    if not isinstance(skills, list) or any(not isinstance(s, str) or not s for s in skills):
        raise AgentFormatError(f'{path}: нужно skills: [] или [a, b] (все — ["*"])')
    mcp = meta.get("mcp", "default")
    if not isinstance(mcp, str) or not mcp.strip():
        raise AgentFormatError(f"{path}: нужен непустой mcp, получено {mcp!r}")
    model = meta.get("model", "")
    if model is None:
        model = ""
    if not isinstance(model, str):
        raise AgentFormatError(f"{path}: model — строка, получено {model!r}")
    raw_max = meta.get("max_rounds", "")
    max_rounds: int | None = None
    if raw_max not in ("", None):
        try:
            max_rounds = int(str(raw_max).strip())
        except ValueError:
            raise AgentFormatError(f"{path}: max_rounds — 1..30, получено {raw_max!r}") from None
        if not 1 <= max_rounds <= 30:
            raise AgentFormatError(f"{path}: max_rounds — 1..30, получено {max_rounds}")
    return Agent(
        name=name,
        title=title.strip(),
        description=description.strip(),
        tools=tuple(tools),
        skills=tuple(skills),
        mcp=mcp.strip(),
        model=model.strip(),
        max_rounds=max_rounds,
        prompt=prompt,
        source=str(path),
    )


@dataclass
class AgentRegistry:
    agents: list[Agent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, agents_dir: Path | str) -> AgentRegistry:
        """Сканировать agents_dir/*/AGENT.md. Битые — пропуск с записью в errors."""
        reg = cls()
        root = Path(agents_dir)
        if not root.is_dir():
            return reg
        for path in sorted(root.glob("*/AGENT.md")):
            try:
                reg.agents.append(parse_agent_file(path))
            except AgentFormatError as e:
                log.warning("скип агента: %s", e)
                reg.errors.append(str(e))
        return reg

    def get(self, name: str) -> Agent | None:
        return next((a for a in self.agents if a.name == name), None)

    @property
    def names(self) -> list[str]:
        return [a.name for a in self.agents]
