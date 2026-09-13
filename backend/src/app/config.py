from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "1c-ai-agent"

    # LLM: любой OpenAI-совместимый эндпоинт.
    # В dev на VPS без GPU — облачная модель и ТОЛЬКО нечувствительные данные.
    # Прод: локальный llama.cpp-server с qwen3.8-27b-1C (см. AGENTS.md).
    llm_base_url: str = "http://localhost:8080/v1"
    llm_api_key: str = "none"
    llm_model: str = "qwen3.8-27b-1C"

    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5432/agentdb"

    # MCP-прокси к 1С (профиль onec в docker-compose.yml).
    onec_mcp_url: str = "http://localhost:8000"


settings = Settings()
