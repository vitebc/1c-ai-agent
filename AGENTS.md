# AGENTS.md

## Проект

ИИ-чат-агент для 1С: вопросы на естественном языке → RAG по базе знаний + запросы/отчёты по данным 1С. Пользователи — сотрудники (роли) и внешние клиенты.

Статус: бэкенд + RAG-скелет + 1С-слой + чат-клиент реализованы (шаги 0–4). Пилот — КА2 (живая база, 7 инструментов, `tools/list` + реальные JSON-ответы проверены, replay 6/6). Сеть Linux↔1С — по `MCP_ONEC_URL` (см. «Окружение»).

## Жёсткие ограничения

- LLM только локально (Ollama / llama.cpp / vLLM), закрытый контур. Никаких облачных API в проде — данные не покидают периметр.
- Интерфейс к моделям — OpenAI-совместимый, провайдер заменяем.
- Модель — русский + function calling (агентская петля); эмбеддинги тоже локальные.
- Права 1С (RLS, профили групп доступа) — на этапе выборки данных агентом, не только в UI.

## Варианты реализации

1. Доработка CFE: https://github.com/andromanpro/1c-ai-connector («ИИкона», function calling + RAG + MCP на BSL), https://github.com/voskorbin/1c-ai-assistant (CFE + Go-шлюз).
2. **Выбран:** свой бэкенд (FastAPI) + pgvector + инструменты 1С; чат — форма в 1С.
3. Платформа как «мозг»: Dify/AnythingLLM — 1С тонкий клиент.

Критерии: закрытый контур, мультисценарность (БЗ + данные/отчёты), сквозные права, поддержка.

## Стек (решение)

- LLM: `sweetand/qwen3.8-27b-1C` (Apache-2.0, GGUF, SFT под BSL/XML/язык запросов, до 262K, tool calling + thinking от базы). Квант: Q4_0 ~16 ГБ VRAM (24 ГБ карта), Q8_0 ~29 ГБ (32 ГБ+). Serving: llama.cpp-server / Ollama (GGUF-only). Самплинг: temperature=0.6, top_p=0.95, top_k=20, repetition_penalty=1.3; thinking off для tool calling. Вне 1С слабее базы — на PoC сравнить с базовой Qwen3.8-27B.
- Эмбеддинги: `deepvk/USER-bge-m3` (TEI CPU, `EMBEDDINGS_PROVIDER=fake` для dev) ; реранкер `BAAI/bge-reranker-v2-m3` — фаза 2.
- Бэкенд: Python 3.12 + FastAPI + uv, `openai`-клиент к локальному OpenAI-endpoint; своя тонкая петля function calling (LangGraph — только если нужен human-in-the-loop). `POST /chat {message, session_id?, user_id?, attachments?[], context_size?, skill?}` → SSE `tool`/`answer`/`done`; `?background=true` → `GET /chat/result/{id}`.
- Скилы: `backend/skills/<name>/SKILL.md` (name/description/tools + промпт, формат — `backend/skills/SKILL.md`); бэкенд (`app/skills/loader.py`) фильтрует `ToolRegistry` и добавляет промпт к базовому. Выбор: явный `skill` из дропдауна 1С → залипший в `sessions.skill_name` → авто-матчинг по `description` (эмбеддинги, top-1). `GET /skills` — список для формы. Новый сценарий — файл без кода и рестарта.
- Хранилище: PostgreSQL + pgvector (чаты/документы/вектора), фильтр прав — WHERE на retrieval. Qdrant — при hybrid/масштабе.
- Инжест: сейчас `.md/.txt` (chunking + fake/TEI), для PDF/DOCX — Docling + Tesseract rus (отложено).
- 1С: MCP-слой — форк `vladimir-kharin/1c_mcp` (MIT, пин `5abe316`, 1.6.1, `mcp>=1.8<2`, 8.3.20+): CFE-ядро (`/hs/mcp/health`, `POST /hs/mcp/rpc`) + наше `A1C_Инструменты` (`a1c_mcp_MCPСервер` по вхождению, `mcp_КонтейнерыИнструментов` по точному имени, `a1c_Инструмент*`): `get_stock_balance` (ТоварыНаСкладах `ВНаличииОстаток`), `get_counterparty` (Контрагенты → Партнер → РасчетыСКлиентами через `АналитикаУчетаПоПартнерам`), `run_skd_report` (РеализацияТоваровУслуг / РасчетыСКлиентами), универсальные `execute_select` (только ВЫБРАТЬ/SELECT + кап 200) + `validate_query` (ПЕРВЫЕ 1), роль `a1c_АгентДоступ` (только `Use` на HTTP-сервис). Живой пилот — список см. `onec/1c_mcp.md`. Важно: инструменты возвращают **только JSON-строку** через `ЗаписьJSON` (массив структур иначе станет «Структура»×N).
- Чат-клиент: форк `КИИ_ТестИИ` + `КИИ_МаркдаунПарсерКлиентСервер` (MIT, andromanpro) → `a1c_МаркдаунПарсер` + `ШаблонДиалога` (пузырьки `user/assistant/error`, `.meta` с токенами/временем, таблицы/код, XSS `ЭкранироватьHTML`). Форма: `Pages` Диалог/Вложения, `Промпт` (multiLine), `ОтветHTML` (VerticalStretch), `Отправить` (Default), `ВыполнятьВФоне` (Switcher, `ФоновыеЗадания`), `РазмерКонтекста` (spin), `ТаблицаВложений` (drag AsFileRef, MIME). BSL `HTTPСоединение POST /chat` + парсинг SSE (`ИзвлечьОтветИзSSE`) + `ОбновитьОтображениеОтвета()`; настройки в `ХранилищеОбщихНастроек`. `HTMLЧат` оставлен как fallback.
- Наблюдаемость: self-hosted Langfuse (отложено).
- Инфра: Docker Compose — `backend` (Linux, `backend/Dockerfile`, `DATABASE_URL=postgres:5432` внутри сети, миграции на старте, healthcheck `/health`), `postgres` (pgvector:pg16), `tei` (профиль `rag`), `mcp-proxy` (профиль `onec`, `:8001→8000`). Порты: `BACKEND_PORT=8000`, `MCP_PROXY_PORT=8001` (разведены).
- Инструменты: ruff, mypy --strict, pytest, pre-commit.

## Схема запросов агентом к данным 1С

- Модель выбирает только из готовых инструментов (function calling, схемы из `onec/schemas.py` → `ToolRegistry`). Причины: RLS делает платформа, модель галлюцинирует имена метаданных.
- Поток: форма (`Промпт` → BSL `ВызватьБэкендЧат`, `%USER_NAME%` = `ИмяПользователя()`) → `POST /chat` + схемы инструментов → tool call → валидация pydantic → `tools/call` к MCP-прокси (`ONEC_MCP_URL`, `ONEC_MODE=mock|live`) → JSON-RPC в 1С под креденшиалами пользователя → BSL повторно валидирует + запрос/остатки (RLS нативно) → компактный JSON (лимит 20/50/200) → в контекст модели, раунды → `a1c_МаркдаунПарсер.ПреобразоватьВHTML` → `ОтветHTML`. История из `messages` ограничивается `context_size*2`.
- Мультибазовость: BSL шлёт `base_name` = `a1c_ЧатФоновый.ИмяИнформационнойБазы()` (БСП `СтроковыеФункцииКлиентСервер.ПараметрыИзСтроки` при наличии модуля, иначе ручной разбор `Ref=`/`File=` из `СтрокаСоединенияИнформационнойБазы()`; всегда НРег). Бэкенд хранит `sessions.base_name` (миграция 0002); сессия чужой базы не переиспользуется — заводится новая, история баз не смешивается. `ToolContext.base_name` зарезервировано под будущую маршрутизацию по базам.
- Классы: (а) отчёты по макетам (каталог в Postgres, фаза 1 — BSL-запросы v1), (б) `get_stock_balance`/`get_counterparty`, (в) универсальные `execute_select`/`validate_query` + `list_metadata_objects`/`get_metadata_structure` (ядро). `ONEC_MODE=mock` — тестовые данные; `live` — прокси.
- Read-only 3 слоя: только читающие инструменты; пользователям 1С — read-only профили (нужен элемент справочника Пользователи + `Чтение` на 7 объектах, иначе `ТекущийПользователь` не ставится и падает `УстановкаПараметровСеанса`); аудит каждого вызова. Перед публикацией сверить `tools/list`.
- Ошибку инструмента — как tool result (модель чинит параметры). Аудит: Langfuse + лог 1С.

## Известные грабли интеграции с 1С

- BSL не стримит HTTP — ответ целиком. Сейчас BSL парсит SSE целиком (`ИзвлечьОтветИзSSE`), при `ВыполнятьВФоне` — через `ФоновыеЗадания.Выполнить(a1c_ЧатФоновыйВызов)` + окно ожидания (как в ИИконе). JS `XMLHttpRequest` в `HTMLЧат` — fallback.
- Тяжёлое — только в фоне, не блокировать форму.
- Точки доступа: HTTP-сервисы / MCP (основное), OData — только простые чтения.
- Отчёты — BSL-запросы v1 (контракт как у СКД, без XML/DSС рисков); переход на `skd-compile` — при нужде в раскладках.
- `1c_mcp`: только `http` в проде (`file`/`httppoll` — тест), регистр базы в URL = публикации (иначе POST→GET), OAuth2 не в `stdio`, password grant удалён (только Authorization Code + PKCE).

## Окружение разработки

- VPS без GPU (Linux): llama-server нет, веса не качаем. Бэкенд — `docker compose up -d backend` (см. `backend/Dockerfile`). LLM для смоуков — облачная OpenAI-модель через `.env` (`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`) только на синтетике.
- GPU-сервер отдельно (5090, 72 ГБ): llama.cpp-server под `qwen3.8-27b-1C` — шаги 1–2.
- Тестовая 1С — Windows-VM (8.3.20+, КА2), требуется элемент Пользователи + чтение 7 объектов + роль `a1c_АгентДоступ` в конфигураторе (шаг 4 `onec/DEPLOY.md`). Связка Linux-бэкенда — по сети (VPN/Tailscale/проброс IIS, `MCP_ONEC_URL` / `ONEC_MCP_URL_COMPOSE=http://mcp-proxy:8000`). Без сети — fallback на Windows-контур (`onec/CHAT.md`). Детали — `onec/README.md`.

## Команды

Backend (из `backend/`):

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src tests scripts/smoke_tools.py
uv run uvicorn app.main:app --reload --app-dir src
uv run python scripts/smoke_tools.py                    # 31 вопрос, ≥0.9
uv run python scripts/smoke_tools.py --replay tests/fixtures/ka2_pilot.json  # 6/6 live-фикстура
uv run python scripts/smoke_tools.py --live             # прокси (ONEC_MCP_URL)
```

Инфра (корень):

```bash
docker compose up -d postgres                 # всегда
docker compose up -d backend                  # + бэкенд (миграции сами, :8000)
docker compose --profile rag up -d            # + TEI
docker compose --profile onec up -d           # + MCP-прокси (профиль onec)
docker compose logs -f backend
```

pre-commit: `pre-commit install && pre-commit run --all-files`. 1С: `onec/smoke_check.py --url http://HOST/base --user agent [--meta]`.

## Git

Remote `origin` https://github.com/vitebc/1c-ai-agent.git, ветка `main`. По шагу: коммит + `git push origin main`, дерево чистое.

## Возможные дополнения (бэклог, из voskorbin/1c-ai-assistant, MIT)

- Контекст открытого объекта: чат из формы документа/справочника шлёт JSON объекта (метаданные + реквизиты + значения) в LLM. Реализация: определяемый тип ссылок + общая команда `ОткрытьЧат` на формах + поле контекста в `POST /chat`.
- Универсальность CFE: язык `Русский` — `Adopted` + `Исправить` при загрузке (UUID под базу); определяемый тип изначально строковый, расширяется ссылочными типами уже в базе.
- Настройки шлюза константами 1С (`АдресШлюза`, таймаут, интервал опроса, лимит вложений/контекста) + персональный промпт в регистре настроек — вместо правок `.env`.
- Polling `/chat/stream` + `/chat/status/{id}` как альтернатива SSE для BSL без стриминга. Go-шлюз не портируем — наш FastAPI покрывает то же.

## Навыки 1С-разработки (cc-1c-skills)

- В `.agents/skills/` 79 скилов из https://github.com/Nikolay-Shirokov/cc-1c-skills (копия, `skills-lock.json`, ветка `port-agents-py` — Python-рантайм, `lxml`+`Pillow`+`psutil` уже в системе; PS с `main` здесь не запустится).
- Для проекта — `cfe-*` (расширение), `skd-*` (отчёты), `meta-*`, `role-*` (read-only), `form-*` (форма чата), `a1c_МаркдаунПарсер` — форк `КИИ_МаркдаунПарсерКлиентСервер` (MIT). `db-*`/`web-*` — только XML без платформы.
- Обновление: clone `port-agents-py` → копировать `.agents/skills/*` → `computedHash` (sha256 SKILL.md) в `skills-lock.json`.

