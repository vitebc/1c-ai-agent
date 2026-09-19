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

Ключевое для локального контура: `ONEC_MODE=mock|live` (моки или прокси
через `ONEC_MCP_URL` + опционально `ONEC_TOKEN`), CORS открыт (`*`) —
чат-форма 1С ходит из HTML-документа.

## Смоук function calling (шаг 1)

Гоняет 24 вопроса на русском через петлю с мок-инструментами 1С, считает долю
попаданий в ожидаемый инструмент (критерий ≥ 0.9):

```bash
uv run python scripts/smoke_tools.py
```

Нужны рабочие `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` в `.env`.
Вопросы — в `scripts/questions.json` (`expected` — имя инструмента или `none`).

Базовый прогон 2026-09-13 (DeepSeek API, `deepseek-flash`, мок-инструменты):
completed 24/24, choice 24/24 = 1.00, clean 24/24 (без ERROR-ретраев).

Прогон 2026-09-13 после шага 2 (+RAG на fake-эмбеддингах, 7 KB-вопросов):
completed 31/31, choice 31/31 = 1.00, clean 31/31. Denial-тест прав
(профиль `sales` спрашивает про документ профиля `accounting`) — утечки нет,
модель честно отвечает «в базе знаний нет».

## Replay на живых данных 1С (без сети до базы)

```bash
uv run python scripts/smoke_tools.py --replay tests/fixtures/ka2_pilot.json
```

Фикстура — реальные ответы тестовой КА2 (сняты `onec/smoke_check.py`),
вопросы — `scripts/replay_questions.json`. Петля идёт через live-адаптер
(`build_onec_tools` + `FakeOnecClient`), LLM настоящий. Регресс шейпинга
и качества ответов после правок BSL.

Прогон 2026-09-13 (deepseek-flash): completed 6/6, choice 6/6 = 1.00.
Модель корректно отработала multi-match (5 стульев одной таблицей),
пустую карточку («не найден») и сложный кейс «долг Лебедева»:
5 поисков по карточке → пусто → отчёт debtors → долг найден.

## RAG-скелет (шаг 2)

```bash
uv run alembic upgrade head   # таблицы users/sessions/messages/documents/chunks
```

Инжест синтетики (`synth_docs/`, профили прав — в `synth_docs/README.md`):

```bash
uv run python - <<'EOF'
import asyncio, sys
sys.path.insert(0, "src")
from pathlib import Path
from app.db.session import SessionFactory
from app.rag import FakeEmbeddings, ingest_file

async def main() -> None:
    for name, profile in {"vozvraty": "all", "sklad": "all", "otchety": "all",
                          "skidki": "sales", "kontragenty": "sales",
                          "debitorka": "accounting"}.items():
        await ingest_file(Path(f"synth_docs/{name}.md"), access_profile=profile,
                          session_factory=SessionFactory, embeddings=FakeEmbeddings())

asyncio.run(main())
EOF
```

Эмбеддинги: `EMBEDDINGS_PROVIDER=fake` (дефолт) или `tei` (`TEI_BASE_URL`,
профиль `rag` в compose). Fake — детерминированные вектора с лексическим
ранжированием: честный тест plumbing'а retrieval, не качества поиска.

Чат: `POST /chat {message, session_id?, user_id?}` — SSE (`tool`/`answer`/`done`),
история пишется в postgres. Профиль прав пользователя берётся из `users`
(`access_profile`, дефолт `all`).

DB-тесты (`test_rag_db.py`, `test_chat_api.py`) требуют поднятый postgres.

## Отложено (нет реальных документов/трафика)

- Docling (PDF/DOCX): инжест сейчас только `.md`/`.txt`; PDF поднимет ошибку
  с подсказкой. Тянуть torch ради синтетики не стали.
- Живой TEI: образ и модель (~3 ГБ) качаем, когда появятся реальные документы.
- Langfuse: трейсинг подключаем, когда будет реальный трафик (шаг 3–4).
