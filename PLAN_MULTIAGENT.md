# План: мультиагентность бэкенда

> Статус: **реализован** (коммит `2be4b39` + развитие: `max_rounds`/`model` на агента,
> `mcp: [default, ...]` — отбор подсерверов агрегатора, `GET /tools` с тегом `server`).
> Файл оставлен как история решения; актуальный формат — `backend/agents/AGENT.md`.

## Решение
- Агенты: `assistant` («Ассистент», дефолт), `analyst` («Аналитик»), `tz-helper` («ТЗ-Помощник»).
- Объявление — файл `backend/agents/<name>/AGENT.md` (как скилы, без рестарта).
- Выбор: явный `agent` из дропдауна 1С > залипший `sessions.agent_name` > дефолт `assistant`. Авто-матчинг по description — НЕ делаем (явный дропдаун по требованию).
- MCP: один сервер, одна точка входа; агент = фильтр `tools` поверх общего `ToolRegistry`. Отдельных URL на агента нет; в формате поле `mcp` резервируем.
- RAG: изоляция по агенту (`documents.agent_name`, NULL = общий).
- Модель: пока одна (`settings.llm_model`), в формате поле `model` как опциональный оверрайд + `get_llm(model_override)`.

## 1. Формат `AGENT.md`
```markdown
---
name: analyst
title: Аналитик
description: анализ продаж и остатков, сводные отчёты
tools: [get_stock_balance, get_counterparty, run_skd_report, execute_select, validate_query, list_metadata_objects, get_metadata_structure, search_knowledge_base]
skills: [zakazy-prokudina]   # [] = без скилов, ["*"] = все
mcp: default                  # резерв, фаза-1 игнорируется
model: qwen3.8-27b-1C         # опционально, дефолт = settings.llm_model
---
<системный промпт агента + 1-2 примера. ЗАМЕНЯЕТ базовый SYSTEM_PROMPT, не дописывается>
```
Правила (как у скилов): `name` латиница/`-` = имя папки; битый файл — пропуск + `errors` в `GET /agents`; `tools` — подмножество реестра, неизвестные → warning; `skills` — имена из `backend/skills`, неизвестные → warning + игнор.

Файлы: `backend/agents/AGENT.md` (описание формата), `assistant/AGENT.md`, `analyst/AGENT.md`, `tz-helper/AGENT.md`.
- `assistant`: все тулзы + все скилы (`["*"]`), промпт = текущий `SYSTEM_PROMPT` (вынести как есть).
- `analyst`: тулзы данных 1С + `search_knowledge_base`, скилы `["*"]` (или `zakazy-prokudina` + будущие), промпт про агрегации/таблицы/периоды.
- `tz-helper`: тулзы = только `[search_knowledge_base]` (без 1С), скилы `[]`, промпт про сбор требований/структуру ТЗ/уточняющие вопросы.

## 2. `app/agents/loader.py` (+ `__init__.py`)
- По образцу `app/skills/loader.py`: `Agent`, `AgentFormatError`, `AgentRegistry {agents, errors, load(), get(), names}`.
- Переиспользовать плоский frontmatter-парсер скилов (вынести общий `_parse_frontmatter` в `app/agents/frontmatter.py` или импортировать из skills — не дублировать).
- `Agent.system_prompt: str`, `allowed_tools: tuple`, `allowed_skills: tuple` (`("*",)` = все), `model: str | None`, `title`, `description`, `source`.
- `AgentRegistry.load(agents_dir)` на каждый запрос (как скилы).

## 3. Конфиг и реестр
- `settings.agents_dir` (дефолт `backend/agents`, как `skills_dir`), `settings.default_agent = "assistant"`.
- `get_agent_registry()` (Depends, перечитывает файлы) + `GET /agents` → `[{name,title,description,tools}]` + `errors` для дропдауна 1С.
- `GET /skills?agent=X` — фильтровать скилы по `allowed_skills` агента (без параметра — все, совместимость).

## 4. `POST /chat`: резолв агент → скил → реестр
- `ChatRequest.agent: str | None` (max 64).
- Порядок: `req.agent` (404 если нет) > `session.agent_name` (файл удалён → сброс + дефолт) > `settings.default_agent`.
- Скил валидируется ВНУТРИ агента: явный `req.skill` обязан быть в `allowed_skills`, иначе 404 `skill not available for agent`; залипший чужой — сброс; авто-матчинг (`skills.match`) только среди скилов агента.
- Фильтр реестра: `registry.subset(agent.allowed_tools ∩ skill.tools?)` — точнее: сначала `subset(agent.tools)`, затем если скил — `subset(skill.tools)` от уже урезанного; `missing` → warning в лог.
- `run_agent`: `extra_system = agent.system_prompt + skill.system_block?` (агент ЗАМЕНЯЕТ `SYSTEM_PROMPT`: добавить параметр `base_system: str = SYSTEM_PROMPT`), плюс `agent_name` в сигнатуру и логи (как `skill_name`).
- Модель: `llm = get_llm()` → если `agent.model` задан, пересобрать клиент с оверрайдом; залогировать.
- RAG: `ToolContext` + `make_kb_search` получают `agent_name`; `retrieve(..., agent_name)`: `WHERE documents.agent_name IS NULL OR = :agent`.
- Ответы: `done: {session_id, agent, skill, ...}`, `GET /chat/result/{id}` + `skill_name`/`agent_name` в `_background_jobs`.

## 5. БД
- Миграция `0004`: `sessions.agent_name VARCHAR(64) NULL`, `documents.agent_name VARCHAR(64) NULL` (индекс по `documents.agent_name`).
- Модели: `ChatSession.agent_name`, `Document.agent_name`.
- Ингест (`ingest_file`, скрипты/synth_docs): параметр `agent_name` (дефолт NULL = общий чанк виден всем агентам).
- Существующие документы остаются общими (NULL) — поведение не меняется до разметки.

## 6. Форма `a1c_Чат`
- Реквизит `Агент` (строка 64) + поле с `DropListButton` над `Скил`; значение по умолчанию `assistant` («Ассистент», показывать `title`, хранить `name`).
- При создании: `GET /agents` → список; `GET /skills?agent=` → скилы; при смене агента — перезаполнить скилы, сбросить `Скил` в «Авто», сохранить настройки.
- Отправка: поле `agent` в обоих путях (`ВызватьБэкендЧат` + `a1c_ЧатФоновый.ВыполнитьЗапрос` — 6-й... фактически 7-й параметр `АгентСтрокой`), пусто не шлём (бэкенд применит дефолт).
- `done.agent` — опционально показать в `.meta` ответа.

## 7. Docker/docs/тесты
- `Dockerfile`: `COPY agents ./agents`.
- `backend/README.md` + `AGENTS.md`: раздел про агентов (формат, выбор, изоляция RAG).
- Тесты `tests/test_agents.py`: парсинг 3 эталонов; битые файлы; резолв (явный/залипший/дефолт/404); скил чужого агента → 404/сброс; фильтр тулзов (`tz-helper` без 1С-тулзов); RAG-изоляция (чанк агента А не виден Б, NULL виден всем); `GET /agents`, `GET /skills?agent=`; `done.agent`.
- Проверки: `pytest`, `ruff check`, `ruff format --check`, `mypy --strict`, `alembic upgrade head`, `cfe-validate`.

## Порядок работ
1. `agents/` + 3 `AGENT.md` + формат-дока.
2. `app/agents/loader.py` (+ общий frontmatter-парсер).
3. Конфиг + `GET /agents` + `GET /skills?agent=`.
4. Миграция 0004 + RAG-изоляция + ингест.
5. `POST /chat` + `run_agent(base_system, agent_name)` + `done.agent`.
6. Форма 1С (Агент + фильтр скилов + фон).
7. Dockerfile/docs/тесты → коммит + push.

## Риски
- `tz-helper` без 1С-тулзов: явный `skill` с 1С-тулзами внутри него → 404 на резолве (проверять пересечение заранее, warning).
- Старые сессии без `agent_name` → дефолт `assistant`, поведение как сейчас.
- Дублирование frontmatter-парсера — вынести общий, иначе разъедется со скилами.
