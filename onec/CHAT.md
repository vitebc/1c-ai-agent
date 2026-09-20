# Чат-клиент (шаг 4)

Форма `a1c_Чат.Форма` в нашем расширении: поле адреса бэкенда + HTML-документ
с чатом. BSL на стриминг не способен — поэтому вся работа в JS внутри
HTML-документа, BSL только подставляет URL и пользователя в шаблон.

## Как устроено

- Макет `HTMLЧат` (TextDocument) — страница чата: CSS, ES5-JS без зависимостей
  (переживёт любой встроенный браузер 1С), транспорт — `XMLHttpRequest`
  с инкрементальным чтением `responseText` (работает даже там, где нет
  fetch/EventSource).
- Модуль формы (`ПриСозданииНаСервере`): подставляет в `%BASE_URL%` значение
  поля `АдресБэкенда` (дефолт `http://localhost:8000`, правится на форме),
  в `%USER_NAME%` — `ИмяПользователя()` (спрашивающий, не сервисный юзер).
- JS шлёт `POST {base}/chat {message, session_id, user_id}`, парсит SSE-кадры
  (`tool` → статус, `answer` → дельты, `done` → session_id), рендерит
  markdown-lite (таблицы, код, bold, заголовки).
- Открытие: пока только через **Все функции** → Обработки → `a1c_Чат`
  (в командный интерфейс не выведена — позже).

## Контур запуска

### Основной — бэкенд на Linux (VPS/сервер)

```bash
cp .env.example .env          # заполнить LLM_*, MCP_ONEC_URL=http://<1С-хост>/base
docker compose up -d postgres backend   # бэкенд на :8000, миграции сами
docker compose logs -f backend
# прокси 1c_mcp — рядом на Linux (порт 8001), тянет 1С по HTTP:
pip install -r /path/to/1c_mcp/src/py_server/requirements.txt
python -m src.py_server http --port 8001 --onec-url http://<iis>/ka2test --onec-username agent --onec-password ...
# .env: ONEC_MODE=live  ONEC_MCP_URL=http://localhost:8001
```

Требует сети Linux → Windows-VM (VPN/Tailscale, проброс порта IIS или SSH-туннель). Если сети нет — см. fallback ниже.

В 1С открыть чат, в поле «Бэкенд» — `http://<linux-хост>:8000`.

### Fallback — всё на Windows (без сети Linux↔1С)

Аналогично, но `docker compose up -d postgres` в Docker Desktop + `uv run uvicorn` и прокси на той же Windows-машине. В поле «Бэкенд» — `http://localhost:8000`.

`ONEC_MODE`: `mock` (тестовые данные, дефолт) / `live` (прокси).

Смоук live-связки (backend/): `uv run python scripts/smoke_tools.py --live`.
