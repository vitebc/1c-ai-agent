"""Тонкая агентская петля с function calling.

Правила (см. AGENTS.md, «Схема запросов»):
- модель выбирает только из готовых инструментов, сырой язык запросов 1С запрещён;
- аргументы валидируются pydantic-схемой инструмента;
- ошибка инструмента возвращается модели как tool result — она чинит параметры
  и повторяет вызов;
- неизвестный инструмент — тоже ошибка в контекст, а не падение.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agent.tools import ToolContext, ToolRegistry
from app.llm import AssistantMessage, ChatLLM

log = logging.getLogger("agent1c.loop")

SYSTEM_PROMPT = (
    "Ты — ассистент пользователей 1С, отвечаешь на русском языке.\n"
    "Данные берёшь ТОЛЬКО из инструментов. Приоритет:\n"
    "1) готовые: get_stock_balance, get_counterparty, run_skd_report — если вопрос про них;\n"
    "2) для любых других данных 1С (документы ЗаказКлиента, Реализация и т.п., "
    "справочники, регистры) — используй execute_select: сначала уточни имена через "
    "list_metadata_objects/get_metadata_structure, затем сформируй ВЫБРАТЬ запрос "
    "и проверь через validate_query.\n"
    "Не выдумывай имена объектов — сверяй через инструменты метаданных. "
    "Если после проверки данных нет — так и скажи.\n"
    "В execute_select параметры (&q) НЕ поддерживаются — подставляй значения литералами "
    "в текст запроса, спецсимволы ПОДОБНО (%, _) экранируй как [%] и [_].\n"
    "Поиск по контрагентам/номенклатуре — нечёткий: разбивай фразу на слова и ищи "
    "ПОДОБНО %слово% по Наименование/НаименованиеПолное, период для заказов не обязателен — "
    "по умолчанию последние 5 по Дата УБЫВ.\n"
    "Если инструмент вернул matches (несколько кандидатов) — покажи их пользователю и спроси, "
    "кого он имел в виду. Запрещено молча выбирать одного кандидата и выдавать его за ответ.\n"
    "Уточняющий вопрос (оставь, убери, отсортируй, покажи детали, посчитай итог) относится "
    "к строкам прошлого ответа из истории диалога — фильтруй/считай по ним, новый широкий "
    "поиск не начинай. Не хватает поля (сумма, статус) — добери его одним точечным "
    "execute_select по уже известным ключам (Номер), а не повторной разведкой.\n"
    "Табличные данные оформляй markdown-таблицей, цифры — как вернулось из инструмента.\n"
    "Если инструмент вернул ERROR — исправь параметры и повтори вызов, не сдавайся сразу."
)


@dataclass
class AgentResult:
    answer: str
    rounds: int
    tool_calls: list[str] = field(default_factory=list)
    # Сколько раз модели вернули ERROR-фидбэк (невалидные аргументы, неизвестный
    # инструмент, падение обработчика). 0 = чисто с первой попытки.
    tool_errors: int = 0


def _preview(content: str | list[dict[str, Any]] | None, limit: int = 500) -> str:
    """Короткий текст для логов: data URI выкидываем, пробелы жмём, режем."""
    if not isinstance(content, str):
        chunks = []
        for part in content or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                chunks.append(str(part.get("text", "")))
            elif part.get("type") == "image_url":
                chunks.append("[image]")
        content = " ".join(chunks)
    text = " ".join(content.split())
    return text if len(text) <= limit else text[:limit] + "…"


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
    user_message: str | list[dict[str, Any]] = "",
    user_id: str = "dev",
    access_profile: str = "all",
    base_name: str = "",
    max_rounds: int = 6,
    history: list[dict[str, Any]] | None = None,
    extra_system: str = "",
    skill_name: str = "",
) -> AgentResult:
    system = SYSTEM_PROMPT + ("\n\n" + extra_system.strip() if extra_system.strip() else "")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    ctx = ToolContext(user_id=user_id, access_profile=access_profile, base_name=base_name)
    called: list[str] = []
    errors = 0
    started = time.monotonic()
    base = base_name or "-"
    skill = skill_name or "-"
    log.info("user=%s base=%s skill=%s q=%s", user_id, base, skill, _preview(user_message))

    for round_no in range(1, max_rounds + 1):
        resp = await llm.complete(messages, registry.schemas())
        messages.append(_assistant_message(resp))
        if not resp.tool_calls:
            elapsed = time.monotonic() - started
            log.info(
                "user=%s base=%s skill=%s rounds=%d tools=%s errors=%d elapsed=%.1fs answered: %s",
                user_id,
                base,
                skill,
                round_no,
                called,
                errors,
                elapsed,
                _preview(resp.content),
            )
            return AgentResult(answer=resp.content or "", rounds=len(called) + 1, tool_calls=called, tool_errors=errors)
        for call in resp.tool_calls:
            called.append(call.name)
            feedback = await _execute_call(registry, ctx, call.name, call.arguments)
            if feedback.startswith(("ERROR", "Ошибка выполнения", "Ошибка:")):
                errors += 1
            log.info(
                "user=%s round=%d tool=%s args=%.300s -> %.300s",
                user_id,
                round_no,
                call.name,
                call.arguments,
                feedback,
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": feedback})

    log.warning(
        "user=%s base=%s skill=%s rounds exhausted: tools=%s errors=%d elapsed=%.1fs",
        user_id,
        base,
        skill,
        called,
        errors,
        time.monotonic() - started,
    )
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
