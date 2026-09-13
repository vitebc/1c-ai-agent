"""Фейковый LLM для тестов: отдаёт заготовленные ответы, пишет входящие."""

from __future__ import annotations

from typing import Any

from app.llm import AssistantMessage


class FakeLLM:
    def __init__(self, script: list[AssistantMessage]) -> None:
        self._script = list(script)
        self.seen_messages: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantMessage:
        # Копия: петля дописывает в тот же список по ходу раундов.
        self.seen_messages.append(list(messages))
        return self._script.pop(0)
