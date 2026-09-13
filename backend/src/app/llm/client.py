"""Клиент LLM через OpenAI-совместимый HTTP API.

Петля агента зависит только от протокола ChatLLM — в тестах подменяется фейком,
провайдер (llama.cpp-server, Ollama, облако) задаётся base_url в конфиге.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # сырой JSON от модели


@dataclass
class AssistantMessage:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatLLM(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantMessage:
        """Один шаг: сообщения + схемы инструментов -> ответ модели."""
        ...


class OpenAICompatibleLLM:
    """AsyncOpenAI-клиент с сэмплингом из карточки qwen3.8-27b-1C."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.6,
        top_p: float = 0.95,
        top_k: int = 20,
        repetition_penalty: float = 1.3,
        enable_thinking: bool = False,
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._top_p = top_p
        self._extra_body: dict[str, Any] = {
            "top_k": top_k,
            "repetition_penalty": repetition_penalty,
        }
        if not enable_thinking:
            # Формат llama.cpp/Ollama для Qwen3: гасим thinking-режим.
            # Остальные провайдеры неизвестное поле игнорируют.
            self._extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantMessage:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "top_p": self._top_p,
            "extra_body": self._extra_body,
        }
        if tools:
            kwargs["tools"] = tools
        resp = await self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (msg.tool_calls or [])
        ]
        return AssistantMessage(content=msg.content, tool_calls=calls)
