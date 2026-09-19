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
    agent_max_rounds: int = 6

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


settings = Settings()
