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


def build_user_content(
    text: str,
    attachments: list[dict[str, str]] | None = None,
) -> str | list[dict[str, Any]]:
    """Сформировать multimodal content для OpenAI-совместимого API.

    - без вложений: str
    - с вложениями: list content parts:
        * {type: text, text: ...} для исходного сообщения
        * {type: image_url, image_url: {url: data:...}} для image/*
        * {type: text, text: "[Вложение: name (mime)]"} для остальных
    Base64 передаём как data URI для image, для документов — текстовый маркер.
    """
    if not attachments:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    for att in attachments:
        filename = att.get("filename") or att.get("name") or "file"
        mime = att.get("mime_type") or att.get("mime") or "application/octet-stream"
        b64 = att.get("content_base64") or att.get("data_base64") or ""
        if mime.startswith("image/") and b64:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
            # Дублируем имя для контекста
            parts.append({"type": "text", "text": f"[Изображение: {filename} ({mime})]"})
        else:
            # Не-image: передаём как текстовый маркер, не льём сырой base64 в промпт
            snippet = b64[:120] + "..." if len(b64) > 120 else b64
            if b64:
                parts.append(
                    {
                        "type": "text",
                        "text": f"[Вложение: {filename} ({mime}) base64:{snippet[:80]}...]",
                    }
                )
            else:
                parts.append({"type": "text", "text": f"[Вложение: {filename} ({mime})]"})
    return parts if parts else text


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
