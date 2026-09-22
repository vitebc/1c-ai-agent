"""Инструменты агента: описание + pydantic-схема аргументов + обработчик.

Схема для модели генерируется из args_model (model_json_schema) — один источник
правды для описания и валидации. Обработчик принимает уже провалидированную
модель; Any в сигнатуре — осознанно (конкретные обработчики сужают тип).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    user_id: str  # идентификатор пользователя 1С из токена сессии
    # Профиль прав для фильтрации retrieval (см. AGENTS.md, «Схема запросов»).
    # Резолвится вызывающей стороной (чат-эндпоинт — из таблицы users).
    access_profile: str = "all"
    # Имя ИБ 1С (НРег): для будущей маршрутизации по базам.
    base_name: str = ""


ToolHandler = Callable[[Any, ToolContext], Coroutine[Any, Any, str]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler

    @property
    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools = {t.name: t for t in tools}

    def schemas(self) -> list[dict[str, Any]]:
        return [t.openai_schema for t in self._tools.values()]

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)
