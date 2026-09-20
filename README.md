# 1C AI Agent

ИИ-чат-агент для 1С: пользователи задают вопросы на естественном языке, агент ищет
ответы по корпоративной базе знаний (RAG) и формирует запросы/отчёты по данным 1С.
Подробности архитектуры и принятых решений — в [AGENTS.md](AGENTS.md).

## Структура

- `backend/` — FastAPI-сервис (agent loop, RAG, MCP-клиент к 1С). Python 3.12 + uv.
- `infra/` — конфиги инфраструктуры (init-скрипты postgres и т.п.).
- `onec/` — сторона 1С: инструкции по подключению тестовой базы, позже — XML-исходники нашего CFE-расширения.
- `.agents/skills/` — скилы 1С-разработки (cc-1c-skills), источник в `skills-lock.json`.
- `docker-compose.yml` — dev-контур на VPS (postgres всегда; `tei` — профиль `rag`; `mcp-proxy` — профиль `onec`).

## Quickstart

```bash
cp .env.example .env          # заполнить LLM_BASE_URL/API_KEY/MODEL и MCP_ONEC_URL
docker compose up -d postgres
# бэкенд — Linux-контейнер (миграции применятся на старте):
docker compose up -d backend  # или локально: cd backend && uv sync && uv run uvicorn app.main:app --reload --app-dir src
docker compose logs -f backend
```

Проверка без Docker (линт/тесты):

```bash
cd backend && uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

Линтеры также гоняются pre-commit: `pre-commit install && pre-commit run --all-files`.

## Окружение разработки

VPS без GPU: локальная модель здесь не поднимается. LLM для разработки и смоуков —
облачная OpenAI-совместимая модель через `.env`, **только синтетические и
нечувствительные данные**. Прод-контур (всё локально, `qwen3.8-27b-1C`) описан
в AGENTS.md и на разработку не влияет.
