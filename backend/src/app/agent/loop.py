"""Тонкая агентская петля с function calling.

Правила (см. AGENTS.md, «Схема запросов»):
- модель выбирает только из готовых инструментов, сырой язык запросов 1С запрещён;
- аргументы валидируются pydantic-схемой инструмента;
- ошибка инструмента возвращается модели как tool result — она чинит параметры
  и повторяет вызов;
- неизвестный инструмент — тоже ошибка в контекст, а не падение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agent.tools import ToolContext, ToolRegistry
from app.llm import AssistantMessage, ChatLLM

SYSTEM_PROMPT = """Ты — ассистент пользователей 1С, отвечаешь на русском языке.
Данные берёшь ТОЛЬКО из инструментов: остатки, карточки контрагентов, отчёты.
Не выдумывай имена объектов метаданных 1С — если инструмента нет, так и скажи.
Табличные данные оформляй markdown-таблицей, цифры — как вернулось из инструмента.
Если инструмент вернул ERROR — исправь параметры и повтори вызов, не сдавайся сразу."""


@dataclass
class AgentResult:
    answer: str
    rounds: int
    tool_calls: list[str] = field(default_factory=list)
    # Сколько раз модели вернули ERROR-фидбэк (невалидные аргументы, неизвестный
    # инструмент, падение обработчика). 0 = чисто с первой попытки.
    tool_errors: int = 0


def _assistant_message(msg: AssistantMessage) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in msg.tool_calls
        ],
    }


async def run_agent(
    *,
    llm: ChatLLM,
    registry: ToolRegistry,
    user_message: str,
    user_id: str = "dev",
    max_rounds: int = 6,
) -> AgentResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    ctx = ToolContext(user_id=user_id)
    called: list[str] = []
    errors = 0

    for _ in range(max_rounds):
        resp = await llm.complete(messages, registry.schemas())
        messages.append(_assistant_message(resp))
        if not resp.tool_calls:
            return AgentResult(answer=resp.content or "", rounds=len(called) + 1, tool_calls=called, tool_errors=errors)
        for call in resp.tool_calls:
            called.append(call.name)
            feedback = await _execute_call(registry, ctx, call.name, call.arguments)
            if feedback.startswith("ERROR"):
                errors += 1
            messages.append({"role": "tool", "tool_call_id": call.id, "content": feedback})

    return AgentResult(
        answer="Не уложился в лимит раундов диалога с инструментами. Попробуйте уточнить вопрос.",
        rounds=max_rounds,
        tool_calls=called,
    )


async def _execute_call(registry: ToolRegistry, ctx: ToolContext, name: str, arguments: str) -> str:
    tool = registry.get(name)
    if tool is None:
        return f"ERROR: неизвестный инструмент '{name}'. Доступны: {registry.names}. Выбери из них."
    try:
        args = tool.args_model.model_validate_json(arguments)
    except ValidationError as e:
        return f"ERROR: невалидные аргументы для '{name}': {e}. Исправь параметры и повтори вызов."
    try:
        return await tool.handler(args, ctx)
    except Exception as e:  # обработчик не должен ронять петлю
        return f"ERROR: инструмент '{name}' завершился ошибкой: {e}. Попробуй изменить параметры."
