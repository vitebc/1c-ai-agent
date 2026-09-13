# Backend — ИИ-чат-агент для 1С

FastAPI-сервис: agent loop (function calling), RAG, MCP-клиент к 1С.

## Разработка

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src tests scripts/smoke_tools.py
uv run uvicorn app.main:app --reload --app-dir src
```

Конфигурация — через env (см. `src/app/config.py`), локально через файл `.env`
в корне репозитория. Пример всех переменных — `../.env.example`.

## Смоук function calling (шаг 1)

Гоняет 24 вопроса на русском через петлю с мок-инструментами 1С, считает долю
попаданий в ожидаемый инструмент (критерий ≥ 0.9):

```bash
uv run python scripts/smoke_tools.py
```

Нужны рабочие `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` в `.env`.
Вопросы — в `scripts/questions.json` (`expected` — имя инструмента или `none`).
