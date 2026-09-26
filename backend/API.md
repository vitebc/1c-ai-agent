# API бэкенда

Базовый URL: `http://<host>:8000` (`BACKEND_PORT`, в compose бэкенд на `:8000`).
Все тела — JSON, кодировка UTF-8. Авторизации нет (закрытый контур);
пользователь 1С передаётся полем `user_id` в теле.

## `GET /health`

Проверка живости (healthcheck compose).

Ответ `200`: `{"status": "ok"}`.

## `GET /tools`

Полный реестр доступных инструментов (динамически).

- `mock`: курируемые моки + `search_knowledge_base` + `get_pattern` (если есть паттерны).
- `live`: курируемые `A1C_Инструменты` + любые `a1c_Инструмент*`/`mcp_КонтейнерыИнструментов` из прокси (схема `inputSchema` из 1С уходит модели напрямую, вызов проксируется) + те же локальные. Новый тул в расширении 1С появится тут **без правки кода бэкенда** — достаточно добавить его имя в `AGENT.md: tools:`.
- `?base_url=http://srvr/Ref` — реестр конкретной базы через прямой JSON-RPC (как в `POST /chat`); мусор → `400`.

Ответ `200`:
```json
{"mode": "live", "tools": [{"name": "execute_select", "server": "default", "description": "...", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]}
```

Имена из этого списка — источник правды для поля `tools` в `AGENT.md`. Тулзы агрегатора (`AGG_MCP_URL`) — полными именами `server__tool` с тегом `server`; в `AGENT.md` агент выбирает их полем `mcp: [default, search-ka-update, ...]` + именами в `tools`. Недоступный агрегатор из списка тихо выпадает (warning в лог, чат живёт на остальных тулзах); список агрегатора кешируется (`AGG_MCP_CACHE_TTL`, дефолт 300с).

## `GET /agents`

Список рантайм-агентов для дропдауна формы 1С. Файлы перечитываются
на каждый запрос — новый `backend/agents/<name>/AGENT.md` виден сразу
(в compose `agents/` примонтирован volume-mount, пересборка не нужна).

Ответ `200`:
```json
{
  "default": "assistant",
  "agents": [
    {
      "name": "assistant",
      "title": "Ассистент",
      "description": "общие вопросы по 1С и базе знаний",
      "tools": ["get_stock_balance", "search_knowledge_base"],
      "mcp": ["default"],
      "skills": ["*"]
    }
  ],
  "errors": []
}
```
- `default` — агент, когда в `POST /chat` поле `agent` пустое.
- `skills: ["*"]` — агенту доступны все скилы; `[]` — ни одного.
- `errors` — битые `AGENT.md` (пропущены, чат не роняют).
- `max_rounds` в `AGENT.md` — оверрайд лимита (пусто = дефолт 15; у `tz-helper` 8).

## `GET /skills`

Список рантайм-скилов (`backend/skills/*/SKILL.md`, тоже без рестарта).
Форма 1С поле `skill` не шлёт (всегда авто), эндпоинт — для диагностики
и API-клиентов.

| Query | Назначение |
|---|---|
| `agent` (опц.) | Фильтр скилов по агенту; неизвестный агент → `404` |

Ответ `200`:
```json
{
  "skills": [{"name": "zakazy-prokudina", "description": "...", "tools": ["get_counterparty"]}],
  "errors": []
}
```

## `POST /chat`

Вопрос → агент → ответ. Два режима: SSE-стрим (форма 1С) и фоновый
(`?background=true` + опрос результата).

Тело запроса:
```json
{
  "message": "покажи пять последних заказов Прокудина",
  "session_id": 12,
  "user_id": "ИвановИИ",
  "attachments": [{"name": "фото.jpg", "mime": "image/jpeg", "data_base64": "..."}],
  "context_size": 5,
  "base_name": "ka2",
  "agent": "assistant",
  "skill": "zakazy-prokudina"
}
```
| Поле | Обяз. | Лимиты | Назначение |
|---|---|---|---|
| `message` | да | 1–20000 | Вопрос пользователя |
| `session_id` | нет | — | Сессия бэкенда (история). Чужая `base_name` → новая сессия |
| `user_id` | нет | дефолт `dev` | `ИмяПользователя()` из 1С; профиль прав из `users.access_profile` |
| `attachments` | нет | ≤10, `content_base64` ≤20MB | Вложения; в БД пишется только имя файла |
| `context_size` | нет | 1–100 | Пар user/assistant в LLM; дефолт — последние 20 пар |
| `base_name` | нет | ≤128 | Имя ИБ 1С (НРег), считает BSL |
| `base_url` | нет | ≤256 | Корень публикации базы (`http://srvr/Ref` из Srvr/Ref строки соединения, регистр Ref точный). Бэкенд ходит в `{base_url}/hs/mcp/rpc` напрямую, минуя прокси: вопрос из базы X отвечает база X. Пусто — штатный путь (mock/прокси). Мусор → `400` |
| `agent` | нет | ≤64 | Агент; пусто → дефолт (`assistant`), залипает в сессии |
| `skill` | нет | ≤64 | Скил; пусто → авто top-1 по description среди скилов агента |

Ошибки: `404` — `session not found`, `agent not found`, `skill not found`,
`skill not available for agent`; `413` — больше 10 вложений.
Предохранитель петли (`agent_max_consecutive_errors`, дефолт 3): после N ошибок
инструментов подряд ответом приходит честное «не могу обратиться к базе 1С»
вместо долбёжки упавшего шлюза.

### Режим SSE (по умолчанию)

`Content-Type: text/event-stream`, события:
- `event: tool` → `{"tool": "<имя>"}` — каждый вызов инструмента;
- `event: answer` → `{"delta": "<кусок ~500 символов>"}` — текст ответа кусками;
- `event: done` → `{"session_id": 12, "agent": "assistant", "skill": "zakazy-prokudina", "model": "qwen3.8-27b-1C", "elapsed_s": 4.2, "prompt_tokens": 1200, "completion_tokens": 150, "total_tokens": 1350, "rounds": 3, "tool_errors": 0}`.
  Токены — сумма `usage` OpenAI-совместимого API по всем раундам (провайдер без usage даёт нули); `elapsed_s` — серверное время выполнения.

Падение LLM не даёт HTTP 500: ошибка приходит обычным `answer`-текстом
с подсказкой про `.env` (`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`).

### Фоновый режим (`POST /chat?background=true`)

Для BSL без стриминга. Ответ `200`: `{"job_id": "...", "session_id": 12, "status": "running", "agent": "assistant"}`.

## `GET /chat/result/{job_id}`

Опрос фоновой задачи.

- `running`: `{"job_id", "status": "running", "session_id"}`;
- `done`: `{"job_id", "status": "done", "session_id", "agent", "skill", "model", "elapsed_s", "prompt_tokens", "completion_tokens", "total_tokens", "answer", "rounds", "tool_calls", "tool_errors"}`;
- `error`: `{"job_id", "status": "error", "error", "session_id"}`;
- неизвестный `job_id` → `404`.
