# Backend — ИИ-чат-агент для 1С

FastAPI-сервис: agent loop (function calling), RAG, MCP-клиент к 1С.

## Разработка

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run uvicorn app.main:app --reload --app-dir src
```

Конфигурация — через env (см. `src/app/config.py`), локально через файл `.env`
в корне репозитория. Пример всех переменных — `../.env.example`.
