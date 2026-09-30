# AGENTS.md

## Проект

ИИ-чат-агент для 1С: вопросы на естественном языке → RAG по базе знаний + запросы/отчёты по данным 1С. Пользователи — сотрудники (роли) и внешние клиенты.

Статус: бэкенд + RAG + 1С-слой + чат-клиент + мультиагентность реализованы. Пилот — КА2 (живая база, `tools/list` + реальные JSON-ответы проверены, replay 6/6). Агенты: assistant/analyst/tz-helper (промпт/тулзы/скилы/MCP-источники из `AGENT.md`, RAG-изолированы). Пулы инструментов: прямой JSON-RPC в базу (`default`, ~18 тулзов: курируемые + динамические `a1c_Инструмент*`) + агрегирующий MCP (`server__tool`: search-*, rlm, ...). Маршрутизация мультибазовая: `base_name`+`base_url` из формы → `resolve_base_root` (мапа `ONEC_BASES` → присланный `base_url`), зеркала — отдельные равноправные базы. Сеть Linux↔1С — прямые `{base_url}/hs/mcp/rpc` под `ONEC_USERNAME`/`ONEC_PASSWORD`; прокси (`MCP_ONEC_URL`, профиль `proxy`, по умолчанию не поднимается — никаких инициативных обращений к 1С без явного запроса) — fallback-путь чата без `base_url`; агрегатор — по `AGG_MCP_URL` (см. «Окружение»).

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
- Бэкенд: Python 3.12 + FastAPI + uv, `openai`-клиент к локальному OpenAI-endpoint; своя тонкая петля function calling (LangGraph — только если нужен human-in-the-loop). `POST /chat {message, session_id?, user_id?, attachments?[], context_size?, base_name?, base_url?, agent?, skill?}` → SSE `tool`/`answer`/`done` (в `done`: `session_id/agent/skill/model/elapsed_s/prompt_tokens/completion_tokens/total_tokens/rounds/tool_errors`); `?background=true` → `GET /chat/result/{id}`. Лимиты петли: `agent_max_rounds` (дефолт 15, оверрайд `max_rounds` в `AGENT.md`) + предохранитель `agent_max_consecutive_errors` (дефолт 3 — стоп с честным ответом вместо долбёжки упавшей 1С). `GET /tools[?base_name=&base_url=]` — живой реестр (имя/`server`/схема; источник правды для `tools` в `AGENT.md`; с базой — реестр именно её), `GET /agents`, `GET /skills?agent=`. Формат API — `backend/API.md`. CORS открыт (`*`, методы `GET/POST/OPTIONS`) — форма ходит из HTML-документа.
- Агенты: `backend/agents/<name>/AGENT.md` (assistant/analyst/tz-helper, формат — `backend/agents/AGENT.md`); промпт агента ЗАМЕНЯЕТ базовый, `tools` режут реестр, `skills` — разрешённые скилы, `model` — опциональный оверрайд, `mcp` — источники инструментов (`default` + подсерверы агрегатора, напр. `[default, search-ka-update, rlm]`). Выбор: явный `agent` из дропдауна 1С (дефолт `assistant`) → залипший в `sessions.agent_name`. RAG изолирован (`documents.agent_name`, NULL — общий). `GET /agents` — список для формы. Новый агент — файл без кода и рестарта.
- Скилы: `backend/skills/<name>/SKILL.md` (name/description/tools + промпт, формат — `backend/skills/SKILL.md`); бэкенд (`app/skills/loader.py`) фильтрует `ToolRegistry` и добавляет промпт к промпту агента. Выбор — авто top-1 по `description`, но только при score выше `skill_match_threshold` (дефолт 0.3); слабый матч — скил не применяется, модель работает полным набором тулзов агента. Залипает в `sessions.skill_name`; поле `skill` в `POST /chat` оставлено для API/тестов, форма 1С его не шлёт. `GET /skills?agent=` — диагностический список. Новый сценарий — файл без кода и рестарта.
- Паттерны: `backend/patterns/<name>.md` (формат — `backend/patterns/README.md`); ленивая подгрузка моделью через тулзу `get_pattern` перед первым `execute_select`, в промпте агентов только указатель. Новый паттерн — файл без кода и рестарта; `get_pattern` есть у `assistant`/`analyst` (у `tz-helper` нет).
- Хранилище: PostgreSQL + pgvector (чаты/документы/вектора), фильтр прав — WHERE на retrieval. Qdrant — при hybrid/масштабе.
- Инжест: сейчас `.md/.txt` (chunking + fake/TEI), для PDF/DOCX — Docling + Tesseract rus (отложено).
- 1С: MCP-слой — форк `vladimir-kharin/1c_mcp` (MIT, пин `5abe316`, 1.6.1, `mcp>=1.8<2`, 8.3.20+): CFE-ядро (`/hs/mcp/health`, `POST /hs/mcp/rpc`) + наше `A1C_Инструменты` (`a1c_mcp_MCPСервер` по вхождению, `mcp_КонтейнерыИнструментов` по точному имени, обработки `a1c_Инструмент*`): `get_stock_balance` (ТоварыНаСкладах `ВНаличииОстаток`), `get_counterparty` (Контрагенты → Партнер → РасчетыСКлиентами через `АналитикаУчетаПоПартнерам`), `run_skd_report` (РеализацияТоваровУслуг / РасчетыСКлиентами), универсальные `execute_select` (только ВЫБРАТЬ/SELECT + кап 200) + `validate_query` (ПЕРВЫЕ 1), из feenlace/mcp-1c (MIT): `execute_query` (&параметры), `get_metadata_tree`, `get_object_structure`, `get_configuration_info` (имя/версия/поставщик/платформа/режим ИБ), `get_event_log`, из OneBridge/thmoscow-byte (MIT): `get_object_by_link`, `get_link_of_object`, `find_references_to_object`, `get_access_rights`, роль `a1c_АгентДоступ` (только `Use` на HTTP-сервис). Живой пилот — список см. `onec/1c_mcp.md`. Важно: инструменты возвращают **только JSON-строку** через `ЗаписьJSON` (массив структур иначе станет «Структура»×N); новая обработка обязательно регистрируется в `Configuration.xml` (ChildObjects) с уникальными UUID/`TypeId`/`ValueId`, иначе «Неизвестный объект метаданных»; один битый контейнер роняет весь `tools/list` ядра (там нет `Попытка`), включая ядерные тулзы.
- Чат-клиент: форк `КИИ_ТестИИ` + `КИИ_МаркдаунПарсерКлиентСервер` (MIT, andromanpro) → `a1c_МаркдаунПарсер` + `ШаблонДиалога` (пузырьки `user/assistant/error`, `.meta` с токенами/временем, таблицы/код, XSS `ЭкранироватьHTML`). Форма: `Pages` Диалог/Вложения, `Промпт` (multiLine), `ОтветHTML` (VerticalStretch), `Отправить` (Default), `ВыполнятьВФоне` (Switcher, `ФоновыеЗадания`), `РазмерКонтекста` (spin), `Агент` (дропдаун из `GET /agents`, дефолт Ассистент; скил всегда авто — бэкенд метит сам среди скилов агента), `ТаблицаВложений` (drag AsFileRef, MIME), баннер `ПредупреждениеБазы` (startup-check, не блокирует форму). BSL `HTTPСоединение POST /chat {message, user_id, base_name, base_url, ...}` + парсинг SSE (`ИзвлечьОтветИзSSE`) + `ОбновитьОтображениеОтвета()`; при старте — `ПроверитьДоступностьБазы()` (`GET /tools?base_name=&base_url=`, URL-кодирование, тело ошибки бэкенда до 300 символов в текст); настройки в `ХранилищеОбщихНастроек`. `HTMLЧат` оставлен как fallback.
- Наблюдаемость: self-hosted Langfuse (отложено).
- Инфра: Docker Compose — `backend` (Linux, `backend/Dockerfile`, `DATABASE_URL=postgres:5432` внутри сети, миграции на старте, healthcheck `/health`), `postgres` (pgvector:pg16), `tei` (профиль `rag`), `mcp-proxy` (профиль `onec`, `:8001→8000`). Порты: `BACKEND_PORT=8000`, `MCP_PROXY_PORT=8001` (разведены).
- Инструменты: ruff, mypy --strict, pytest, pre-commit, codegraph (граф кода бэкенда: `codegraph query/explore`; BSL не индексируется, только Python).

## Схема запросов агентом к данным 1С

- Модель выбирает только из готовых инструментов (function calling, схемы из `onec/schemas.py` → `ToolRegistry`). Причины: RLS делает платформа, модель галлюцинирует имена метаданных. Правило схем: курируемая pydantic-схема обязана зеркалить требования BSL — что BSL читает безусловно (`Аргументы.x` без `.Свойство()`), то в схеме `required` + допустимые значения в `description` (бэкенд не шлёт `None`, опущенный параметр = «Поле объекта не обнаружено» в 1С).
- Поток: форма (`Промпт` → BSL `ВызватьБэкендЧат`, `%USER_NAME%` = `ИмяПользователя()`) → `POST /chat` + схемы инструментов → tool call → валидация pydantic → прямой JSON-RPC в `{base_url}/hs/mcp/rpc` (`JsonRpcOnecClient`, `ONEC_USERNAME`/`ONEC_PASSWORD`; без `base_url` — штатный путь `ONEC_MODE=mock|live` через `ONEC_MCP_URL`) → JSON-RPC в 1С → BSL повторно валидирует + запрос/остатки (RLS нативно) → компактный JSON (лимит 20/50/200) → в контекст модели, раунды → `a1c_МаркдаунПарсер.ПреобразоватьВHTML` → `ОтветHTML`. История из `messages` ограничивается `context_size*2`. Вложения: `attachments[] {name, mime, content_base64≤20MB (алиас `data_base64`), url?}` (≤10 шт, иначе 413; в БД только имя файла).
- Мультибазовость: BSL шлёт `base_name` = `a1c_ЧатФоновый.ИмяИнформационнойБазы()` (БСП `СтроковыеФункцииКлиентСервер.ПараметрыИзСтроки` при наличии модуля, иначе ручной разбор `Ref=`/`File=` из `СтрокаСоединенияИнформационнойБазы()`; всегда НРег) + `base_url` = `a1c_ЧатФоновый.АдресПубликацииБазы()` (`http://Srvr/Ref`, регистр Ref точный — в URL критичен; файловая ИБ — пусто). Бэкенд хранит `sessions.base_name` (миграция 0002); сессия чужой базы не переиспользуется — заводится новая, история баз не смешивается. Резолв адреса: мапа исключений `ONEC_BASES` (только нестандартные публикации) побеждает присланное, иначе валидный `base_url`; имя без адреса — громкая 400 с эхом, сессия не заводится; пусто всё — штатный путь. Форма при старте проверяет себя `GET /tools?base_name=&base_url=` (баннер при недоступности). С `base_url` бэкенд ходит в `{base_url}/hs/mcp/rpc` напрямую через `JsonRpcOnecClient` (Basic, `ONEC_USERNAME`/`ONEC_PASSWORD` единые; per-user RLS — следующим шагом), минуя прокси: вопрос из базы X отвечает база X, зеркала — отдельные равноправные базы.
- Классы: (а) отчёты по макетам (каталог в Postgres, фаза 1 — BSL-запросы v1), (б) `get_stock_balance`/`get_counterparty`, (в) универсальные `execute_select`/`execute_query`/`validate_query` + `list_metadata_objects`/`get_metadata_structure` (ядро) + `get_metadata_tree`/`get_object_structure`/`get_configuration_info`/`get_event_log` (feenlace), (г) навигация/права OneBridge, (д) тулзы агрегатора `server__tool` (кодовые поиски, rlm-сессии — без RLS базы, только код) + локальные `search_knowledge_base`/`get_pattern` (вне отбора по `mcp`, всегда доступны). `ONEC_MODE=mock` — тестовые данные; `live` — прокси (`ONEC_MCP_URL`, внутри compose `ONEC_MCP_URL_COMPOSE=http://mcp-proxy:8000`); прямые вызовы баз — всегда live-JRPC под `ONEC_USERNAME`/`ONEC_PASSWORD`; агрегатор — `AGG_MCP_URL` (пусто — выкл, TTL-кэш `AGG_MCP_CACHE_TTL`, падение агрегатора чат не роняет).
- Read-only 3 слоя: только читающие инструменты; пользователям 1С — read-only профили (нужен элемент справочника Пользователи + `Чтение` на 7 объектах, иначе `ТекущийПользователь` не ставится и падает `УстановкаПараметровСеанса`); аудит каждого вызова. Перед публикацией сверить `tools/list`.
- Известные грабли BSL: **`Новый Массив(...)` с аргументами недопустим** (конструктор без параметров) — список собирается `Добавить`; ошибка маскируется под «Ошибка при вызове конструктора (Массив)» и выглядит как «инструмент сломан». Плюс грабли языка запросов — см. «Особенности языка запросов 1С».
- Ошибку инструмента — как tool result (модель чинит параметры). Аудит: Langfuse + лог 1С.

## Известные грабли интеграции с 1С

- BSL не стримит HTTP — ответ целиком. Сейчас BSL парсит SSE целиком (`ИзвлечьОтветИзSSE`), при `ВыполнятьВФоне` — через `ФоновыеЗадания.Выполнить(a1c_ЧатФоновыйВызов)` + окно ожидания (как в ИИконе). JS `XMLHttpRequest` в `HTMLЧат` — fallback.
- Тяжёлое — только в фоне, не блокировать форму.
- Точки доступа: HTTP-сервисы / MCP (основное), OData — только простые чтения.
- Отчёты — BSL-запросы v1 (контракт как у СКД, без XML/DSС рисков); переход на `skd-compile` — при нужде в раскладках.
- `1c_mcp`: только `http` в проде (`file`/`httppoll` — тест), регистр базы в URL = публикации (иначе POST→GET), OAuth2 не в `stdio`, password grant удалён (только Authorization Code + PKCE).

## Окружение разработки

- Тесты и линт — на этом сервере (`/root/project/1c-ai-agent`, `cd backend && uv run pytest`). Удалённый сервер — только по явной просьбе: `ssh test@100.85.239.61`, проект `/home/test/project/1c-ai-agent` (там же `.env`, бэкапы `.env.bak-*`).
- VPS без GPU (Linux): llama-server нет, веса не качаем. Бэкенд — `docker compose up -d backend` (см. `backend/Dockerfile`). LLM для смоуков — облачная OpenAI-модель через `.env` (`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`) только на синтетике.
- GPU-сервер отдельно (5090, 72 ГБ): llama.cpp-server под `qwen3.8-27b-1C` — шаги 1–2.
- Тестовая 1С — Windows-VM (8.3.20+, КА2), требуется элемент Пользователи + чтение 7 объектов + роль `a1c_АгентДоступ` в конфигураторе (шаг 4 `onec/DEPLOY.md`). Связка Linux-бэкенда — по сети (VPN/Tailscale/проброс IIS; прямые вызовы — `ONEC_USERNAME`/`ONEC_PASSWORD` + `ONEC_BASES` для исключений, прокси — `MCP_ONEC_URL` / `ONEC_MCP_URL_COMPOSE=http://mcp-proxy:8000`; агрегатор — `AGG_MCP_URL`, см. `.env.example`). Без сети — fallback на Windows-контур (`onec/CHAT.md`). Детали — `onec/README.md`. Референсные выгрузки чужих MCP (OneBridge, feenlace) — в `data/` (в git не коммитятся).

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
uv run python scripts/smoke_tools.py --live             # прямые вызовы/прокси (ONEC_* / ONEC_MCP_URL)
```

Инфра (корень):

```bash
docker compose up -d postgres                 # всегда
docker compose up -d backend                  # + бэкенд (миграции сами, :8000)
docker compose --profile rag up -d            # + TEI
# MCP-прокси по умолчанию НЕ поднимается: никаких инициативных обращений к 1С
# без явного запроса со стороны 1С. Только при необходимости (fallback-путь
# чата без base_url): docker compose --profile proxy up -d mcp-proxy
docker compose logs -f backend
```

pre-commit: `pre-commit install && pre-commit run --all-files`. 1С: `onec/smoke_check.py --url http://HOST/base --user agent [--meta]` (Python, без зависимостей) или PowerShell `onec/test_rpc.ps1` (всё зашито: `tools/list` + `get_configuration_info` + пробный `execute_select`) / `onec/smoke_check_rpc.ps1` (параметризованный `tools/list|tools/call`). Валидация форм/расширения: скилы `form-validate`, `cfe-validate` из `.agents/skills/`.

## Git

Remote `origin` https://github.com/vitebc/1c-ai-agent.git, ветка `main`. По шагу: коммит + `git push origin main`, дерево чистое.

## Свежесть расширения 1С (обязательно)

При ЛЮБОМ изменении `onec/ext/` (BSL/XML) — до коммита прогнать
`cd backend && uv run python scripts/bump_ext_version.py`: он пишет хеш последнего
коммита, тронувшего папку, в `onec/ext/ExtVersion.txt` и добавляет файл в индекс —
коммитится вместе с правкой. Расширение хранит версию в ОбщемРеквизите `ВерсияКоммита` менеджера обработки
`a1c_ИнструментДерево` (заполняется при загрузке из `ExtVersion.txt`), тулза
`get_extension_version` отдаёт её модели; бэкенд-тулза `check_extension_freshness`
(локальная, у assistant/analyst) сравнивает с git и заставляет модель проверить
свежесть ПЕРЕД первым обращением к данным. Без бампа сравнение не работает —
база молча остаётся на старом коде.

## Возможные дополнения (бэклог, из voskorbin/1c-ai-assistant, MIT)

- Контекст открытого объекта: чат из формы документа/справочника шлёт JSON объекта (метаданные + реквизиты + значения) в LLM. Реализация: определяемый тип ссылок + общая команда `ОткрытьЧат` на формах + поле контекста в `POST /chat`.
- Универсальность CFE: язык `Русский` — `Adopted` + `Исправить` при загрузке (UUID под базу); определяемый тип изначально строковый, расширяется ссылочными типами уже в базе.
- Настройки шлюза константами 1С (`АдресШлюза`, таймаут, интервал опроса, лимит вложений/контекста) + персональный промпт в регистре настроек — вместо правок `.env`.
- Polling `/chat/stream` + `/chat/status/{id}` как альтернатива SSE для BSL без стриминга. Go-шлюз не портируем — наш FastAPI покрывает то же.

## Незакрытые задачи

Живой список — в [`TODO.md`](TODO.md) (обновлён 2026-09-29). Не дублирую здесь,
чтобы не расходились. Главное, что блокирует: расширение с BSL-фиксами `2064243`
не перезалито в базу; правки агентов/скилов на сервере не в git.

## Особенности языка запросов 1С (проверено пробами, не догадками)

Агент пишет запросы в тексте `execute_select`/`execute_query`; эти правила
продублированы в `backend/patterns/query-patterns.md` (грузятся моделью) и
`onec/1c_mcp.md` (журнал находок). Ключевое:

- `ПЕРВЫЕ` — **только сразу после `ВЫБРАТЬ`**, не после имени таблицы.
- Подсчёт строк — **`СУММА(1) КАК КЗ`**, а не `СЧЁТЧИК`/`ПОДСЧИТАТЬ` (в проверенных
  базах те дают синтаксическую ошибку).
- Группировка — **`СГРУППИРОВАТЬ ПО`** с буквой «С» (без неё ошибка `"ПО"`).
- Незаполненное поле — **`ГДЕ <Поле> ЕСТЬ NULL`**; `ЕСТЬ НЕОПРЕДЕЛЕНО` не поддерживается.
- **Перечисления (`Статус`, `ТипДоговора`) не фильтруются ни строкой, ни полным именем**
  (строкой — пусто, полным именем — «Поле не найдено»): фактические значения даёт
  только `СГРУППИРОВАТЬ ПО <Поле>`. Отбор по перечислению невозможен.
- Переводы строк и табуляция разрешены — ломает только неверное положение конструкций.
- Имена реквизитов и допустимые значения — **только** из `get_metadata_structure`
  и группировок. Формулировки ТЗ модель подсказывать не должна: в КА 2.5 нет
  `РабочееНаименование`/`ТекущееСостояние`/`СрокДействия`/`ВидДоговора`/`ВидКонтрагента`
  (есть `ТипДоговора`, `Статус`, `ДатаОкончанияДействия`).

## Навыки 1С-разработки (cc-1c-skills)

- В `.agents/skills/` 79 скилов из https://github.com/Nikolay-Shirokov/cc-1c-skills (копия, `skills-lock.json`, ветка `port-agents-py` — Python-рантайм, `lxml`+`Pillow`+`psutil` уже в системе; PS с `main` здесь не запустится).
- Для проекта — `cfe-*` (расширение), `skd-*` (отчёты), `meta-*`, `role-*` (read-only), `form-*` (форма чата), `a1c_МаркдаунПарсер` — форк `КИИ_МаркдаунПарсерКлиентСервер` (MIT). `db-*`/`web-*` — только XML без платформы.
- Обновление: clone `port-agents-py` → копировать `.agents/skills/*` → `computedHash` (sha256 SKILL.md) в `skills-lock.json`.

