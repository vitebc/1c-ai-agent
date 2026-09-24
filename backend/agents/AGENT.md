# Формат агента чат-агента

Агент = папка `backend/agents/<name>/` с файлом `AGENT.md`. Новый агент —
новый файл, без кода и рестарта (бэкенд перечитывает папку на каждый запрос).

```markdown
---
name: analyst
title: Аналитик
description: анализ продаж и остатков, сводные отчёты
tools: [get_stock_balance, get_counterparty, run_skd_report, execute_select, validate_query, list_metadata_objects, get_metadata_structure, search_knowledge_base]
skills: [zakazy-prokudina]
mcp: [default, search-ka-update, rlm]
model: qwen3.8-27b-1C
max_rounds:
---
<текст: системный промпт агента + 1-2 примера. ЗАМЕНЯЕТ базовый SYSTEM_PROMPT.>
```

Правила:

- `name` — латиница/цифры/`-`, обязан совпадать с именем папки.
- `title` — человекочитаемое имя для дропдауна 1С (может быть на русском).
- `description` — одно-два предложения (для справки в `GET /agents`).
- `tools` — подмножество имён из `ToolRegistry` (см. `GET /tools`). Тулзы агрегатора — полными именами `server__tool` (напр. `search-ka-update__semantic_find`). Неизвестные имена игнорируются с warning в лог.
- `skills` — имена из `backend/skills`; `[]` — без скилов, `["*"]` — все скилы. Неизвестные игнорируются с warning.
- `mcp` — источники инструментов: `default` (прокси 1С) + имена подсерверов агрегатора (`AGG_MCP_URL`), напр. `mcp: [default, search-ka-update, rlm]`. Одиночная строка `mcp: default` тоже валидна. Тулза попадает агенту только если её сервер в этом списке (иначе warning + отсев); локальные (`search_knowledge_base`, `get_pattern`) доступны всегда.
- `model` — опциональный оверрайд `settings.llm_model`. Пусто — модель из конфига.
- `max_rounds` — опциональный оверрайд `settings.agent_max_rounds` (1–30). Пусто — дефолт.
- Тело после второго `---` — системный промпт агента, ЗАМЕНЯЕТ базовый. Может быть пустым (тогда базовый).
- Поддерживается только этот плоский поднабор frontmatter (без вложенностей и многострочников).
- Битый файл не роняет чат: агент пропускается, причина — в логе (`agents.errors`, см. `GET /agents`).
