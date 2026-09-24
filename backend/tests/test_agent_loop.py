"""Тесты агентской петли с фейковым LLM — сеть не нужна."""

from __future__ import annotations

import asyncio

from app.agent import AgentResult, ToolRegistry, run_agent
from app.llm import AssistantMessage, ToolCall
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM


def _run(llm: FakeLLM, question: str = "тест", max_rounds: int = 6) -> AgentResult:
    return asyncio.run(
        run_agent(
            llm=llm,
            registry=ToolRegistry(MOCK_ONEC_TOOLS),
            user_message=question,
            max_rounds=max_rounds,
        )
    )


def test_answer_without_tools() -> None:
    llm = FakeLLM([AssistantMessage(content="Привет!")])
    res = _run(llm, "привет")
    assert res.answer == "Привет!"
    assert res.tool_calls == []
    assert res.rounds == 1


def test_single_tool_round_trip() -> None:
    llm = FakeLLM(
        [
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="c1", name="get_stock_balance", arguments='{"sku": "стул"}')],
            ),
            AssistantMessage(content="Остаток: 42+7."),
        ]
    )
    res = _run(llm, "сколько стульев?")
    assert res.tool_calls == ["get_stock_balance"]
    assert "42" in res.answer
    # tool result попал в контекст второго шага
    tool_msgs = [m for m in llm.seen_messages[1] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and "Основной" in str(tool_msgs[0]["content"])


def test_invalid_args_then_retry() -> None:
    llm = FakeLLM(
        [
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="c1", name="get_stock_balance", arguments='{"sku": "x"}')],
            ),
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="c2", name="get_stock_balance", arguments='{"sku": "стул офисный"}')],
            ),
            AssistantMessage(content="Готово."),
        ]
    )
    res = _run(llm, "остатки?")
    assert res.answer == "Готово."
    assert res.tool_calls == ["get_stock_balance", "get_stock_balance"]
    feedback = str(llm.seen_messages[1][-1]["content"])
    assert "ERROR" in feedback and "невалидные аргументы" in feedback


def test_unknown_tool_reported_to_model() -> None:
    llm = FakeLLM(
        [
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="c1", name="teleport", arguments="{}")],
            ),
            AssistantMessage(content="Такого инструмента нет."),
        ]
    )
    res = _run(llm, "телепортируй")
    assert res.answer == "Такого инструмента нет."
    feedback = str(llm.seen_messages[1][-1]["content"])
    assert "неизвестный инструмент" in feedback


def test_max_rounds_guard() -> None:
    script = [
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id=f"c{i}", name="get_stock_balance", arguments='{"sku": "стул"}')],
        )
        for i in range(10)
    ]
    llm = FakeLLM(script)
    res = _run(llm, "зацикли меня", max_rounds=3)
    assert res.rounds == 3
    assert res.tool_calls == ["get_stock_balance"] * 3
    assert "лимит раундов" in res.answer


def test_registry_schemas() -> None:
    reg = ToolRegistry(MOCK_ONEC_TOOLS)
    assert set(reg.names) >= {"get_counterparty", "get_stock_balance", "run_skd_report"}
    assert {s["function"]["name"] for s in reg.schemas()} == set(reg.names)
    assert reg.get("nope") is None
    assert "get_metadata_tree" in reg.names
    assert "execute_query" in reg.names
    assert "get_configuration_info" in reg.names
