from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "1c-ai-agent"

    # LLM: любой OpenAI-совместимый эндпоинт.
    # В dev на VPS без GPU — облачная модель и ТОЛЬКО нечувствительные данные.
    # Прод: локальный llama.cpp-server с qwen3.8-27b-1C (см. AGENTS.md).
    llm_base_url: str = "http://localhost:8080/v1"
    llm_api_key: str = "none"
    llm_model: str = "qwen3.8-27b-1C"

    # Сэмплинг из карточки qwen3.8-27b-1C. temperature/top_p — стандартные поля
    # OpenAI API; остальное уходит через extra_body (llama.cpp-server понимает,
    # облачные провайдеры лишние поля обычно игнорируют).
    llm_temperature: float = 0.6
    llm_top_p: float = 0.95
    llm_top_k: int = 20
    llm_repetition_penalty: float = 1.3
    # Thinking-режим Qwen3.8: для tool calling и структурированных задач — off.
    llm_enable_thinking: bool = False

    # Агентская петля.
    agent_max_rounds: int = 15

    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5432/agentdb"

    # Эмбеддинги: 'fake' (dev/test без моделей) или 'tei' (профиль rag в compose).
    embeddings_provider: str = "fake"
    tei_base_url: str = "http://localhost:8081"

    # MCP-прокси к 1С (профиль onec в docker-compose.yml).
    onec_mcp_url: str = "http://localhost:8000"
    # Режим инструментов 1С: 'mock' (тестовые данные) или 'live' (прокси).
    # Live требует доступного прокси; токен — только при MCP_AUTH_MODE=oauth2.
    onec_mode: str = "mock"
    onec_token: str | None = None

    # Агрегирующий MCP-сервер (подсерверы server__tool, напр. search-ka-update, rlm).
    # Пусто — отключён. Агент выбирает подсерверы полем mcp в AGENT.md.
    agg_mcp_url: str = ""
    agg_mcp_token: str | None = None
    # TTL кэша tools/list агрегатора, сек (ответ тяжёлый: 100+ тулзов).
    agg_mcp_cache_ttl: int = 300

    # Рантайм-скилы чат-агента (backend/skills/*/SKILL.md). Перечитываются на каждый запрос.
    skills_dir: str = str(Path(__file__).resolve().parent.parent.parent / "skills")
    # Рантайм-агенты (backend/agents/*/AGENT.md). Перечитываются на каждый запрос.
    agents_dir: str = str(Path(__file__).resolve().parent.parent.parent / "agents")
    # Папка паттернов ленивой подгрузки (backend/patterns/*.md). Тоже на каждый запрос.
    patterns_dir: str = str(Path(__file__).resolve().parent.parent.parent / "patterns")
    # Агент по умолчанию (явный дропдаун 1С; пусто в запросе = этот).
    default_agent: str = "assistant"

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def _coerce_api_key(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        s = v.strip()
        if s == "" or s == "change-me":
            return "none"
        return s

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def _coerce_base_url(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        s = v.strip()
        if s == "" or s == "https://api.example.com/v1":
            return "http://localhost:8080/v1"
        return s


settings = Settings()
