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

## Локальный контур (сети VPS↔VM нет)

Всё крутится на Windows-машине пользователя:

```bat
:: 1. Postgres (docker desktop) + миграции
docker compose up -d postgres
cd backend && uv sync && uv run alembic upgrade head

:: 2. .env рядом с backend (пример значений)
:: LLM_BASE_URL=https://...  LLM_API_KEY=...  LLM_MODEL=...
:: DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5432/agentdb
:: EMBEDDINGS_PROVIDER=fake  ONEC_MODE=live  ONEC_MCP_URL=http://localhost:8001

:: 3. Бэкенд (порт 8000)
uv run uvicorn app.main:app --app-dir src --port 8000

:: 4. Прокси 1c_mcp (отдельная консоль, каталог форка, порт 8001)
pip install -r src\py_server\requirements.txt
python -m src.py_server http --port 8001 --onec-url http://<iis>/ka2test --onec-username agent --onec-password ...
```

`ONEC_MODE`: `mock` (тестовые данные, дефолт) / `live` (прокси).
В 1С открыть чат, в поле «Бэкенд» — `http://localhost:8000`.

Смоук live-связки (там же, backend/): `uv run python scripts/smoke_tools.py --live`.
