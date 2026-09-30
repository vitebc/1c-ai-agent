/root/.opencode/plan/skill-writer-agent.md   [----] 11 L:[  1+32  33/ 51] *(3520/5240b) 1089 0x441                                                           [*][X]
# План: агент skill-writer

Создать агента `skill-writer`, который **генерирует текст файлов в чате** (AGENT.md, SKILL.md, паттерны) по правилам проекта. Агент не пишет файлы на диск — выдаёт

## Местоположение агента
- `backend/agents/skill-writer/AGENT.md`

## Возможности агента
1. **Знает форматы** — AGENT.md, SKILL.md, pattern.md (frontmatter + body, правила из `backend/agents/AGENT.md`, `backend/skills/SKILL.md`, `backend/patterns/READM
2. **Знает все инструменты** — из `ToolRegistry` (core: get_stock_balance, get_counterparty, run_skd_report, execute_select, validate_query, list_metadata_objects,
3. **Знает 1С-паттерны запросов** — из `query-patterns.md`: даты `ДАТА(ГГГГ,М,Д)`, `ПЕРВЫЕ` сразу после `ВЫБРАТЬ`, `СГРУППИРОВАТЬ ПО`, `СУММА(1)`, экранирование `[
4. **Знает типовые BSL-паттерны** — из существующих скилов (заказы клиента, аудит НСИ d44-44-151 и др.)
5. **Генерирует валидный контент** — правильный frontmatter, корректные имена тулзов, ссылки на разведку метаданных

## Конфигурация агента (frontmatter AGENT.md)
```yaml
name: skill-writer
title: Написание скилов/агентов
description: генерация AGENT.md, SKILL.md, паттернов по правилам проекта (вывод в чат)
tools: [search_knowledge_base, get_pattern]
skills: []
mcp: default
model:
max_rounds: 8
```

## Системный промпт (ключевые пункты)
- Ты — генератор файлов конфигурации агентов/скилов/паттернов 1С-ассистента. **Результат выводишь в чате** как markdown-блоки.
- Знаешь форматы: `backend/agents/AGENT.md`, `backend/skills/SKILL.md`, `backend/patterns/README.md`.
- Знаешь все инструменты из `GET /tools` (core, search-ka-update__*, rlm__*, локальные).
- Знаешь синтаксис запросов 1С из `query-patterns`: даты `ДАТА(ГГГГ,М,Д)`, `ПЕРВЫЕ` после `ВЫБРАТЬ`, `СГРУППИРОВАТЬ ПО`, `СУММА(1)`, экранирование `[%]` `[_]`, `va
- При запросе «сделай скил для X» — уточняй: цель, какие данные/таблицы, какие инструменты нужны, есть ли примеры. Выдаёшь готовый `SKILL.md` (frontmatter + body)
- При запросе «сделай агента для Y» — уточняй: роль, набор тулзов, mcp-серверы, скилы, оверрайд модели/раундов. Выдаёшь `AGENT.md`.
- При запросе «сделай паттерн для Z» — выдаёшь `.md` для `backend/patterns/`.
- Всегда проверяй имена тулзов по реестру (если не уверен — напиши, что имя надо проверить через `GET /tools`).
- Не выдумывай имена метаданных 1С — в скилах пиши: «сверь через list_metadata_objects/get_metadata_structure».

## Шаги реализации
1. Создать `backend/agents/skill-writer/AGENT.md` с frontmatter + системным промптом
2. Проверить через `GET /agents` — агент появился в дропдауне
3. Протестировать в чате: «сделай скил для проверки остатков по складам» → проверить валидность SKILL.md
4. Опционально: добавить скил `skill-writer-helper` с примерами, если нужно

## Файлы для создания
- Только `backend/agents/skill-writer/AGENT.md` (изменений кода не требуется)

## Верификация
- `uv run pytest backend/tests/test_agents.py -v` — агент загружается без ошибок
- Ручная: `curl localhost:8000/agents` → есть `skill-writer`
- Чат-тест: просим агента сгенерировать скил, проверяем соответствие формату






 1Help           2Save           3Mark           4Replac         5Copy            6Move           7Search         8Delete         9PullDn         10Quit