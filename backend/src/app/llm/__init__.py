"""Клиент LLM через OpenAI-совместимый HTTP API. Реализация — в client.py."""

from app.llm.client import AssistantMessage, ChatLLM, OpenAICompatibleLLM, ToolCall, build_user_content

__all__ = ["AssistantMessage", "ChatLLM", "OpenAICompatibleLLM", "ToolCall", "build_user_content"]
