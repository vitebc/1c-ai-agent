# Чат-клиент (шаг 4, форк ИИконы)

Форма `a1c_Чат.Форма` — форк `КИИ_ТестИИ` из [andromanpro/1c-ai-connector](https://github.com/andromanpro/1c-ai-connector) (MIT). BSL на стриминг не способен — поэтому гибрид: BSL + JS.

## Что дёрнули

- **Вёрстка:** `Pages` с вкладками `Диалог` / `Вложения`, `HTMLDocumentField ОтветHTML` на весь VerticalStretch, группа `ГруппаКоманды` с `Отправить` (DefaultButton), `ВыполнятьВФоне` (Switcher), `РазмерКонтекста` (spin), `Очистить`/`ПрикрепитьФайлы`.
- **Рендер истории на сервере:** `ШаблонДиалога` (HTML+CSS пузырьки `message user/assistant/error`, `.role`, `.meta`, таблицы/код/цитаты) + `a1c_МаркдаунПарсер` (форк `КИИ_МаркдаунПарсерКлиентСервер`, MIT) с `ПреобразоватьВHTML()` и XSS-защитой `ЭкранироватьHTML()`. Пустое состояние `История диалога пуста`.
- **Мета-строка:** `⚡ Токены: X | ⏱ Время: Yс | ⚒ Модель: Z` под каждым ответом.
- **Настройки:** `ХранилищеОбщихНастроек` (Эксперт/ВыполнятьВФоне/РазмерКонтекста), загрузка/сохранение в `ПриСозданииНаСервере`/`ПередЗакрытием`.
- **Вложения:** `ТаблицаВложений` (Отправлять, Направление, Имя, MIME, Размер, Адрес во временном хранилище), drag-and-drop `AsFileRef`, `ПрикрепитьФайлы` через `ФайловаяСистемаКлиент`, `MIMEПоИмениФайла`, `КонтентВложения` для мультимодала.
- **Фон:** `ДлительныеОперации` — если `ВыполнятьВФоне`, BSL не виснет: `ФоновыеЗадания.Выполнить(a1c_ЧатФоновыйВызов)` + ожидание.

## Как устроено сейчас

- Модуль формы: `АдресБэкенда` (дефолт `http://localhost:8000`) + `%USER_NAME%` = `ИмяПользователя()` (спрашивающий). `ОбновитьОтображениеОтвета()` генерит `ОтветHTML` через `ПолучитьМакет("ШаблонДиалога")` → `[MESSAGES]` → `СформироватьHTMLСообщения()` → `a1c_МаркдаунПарсер`.
- Отправка: `Отправить` → `ВызватьБэкендЧат()` — BSL делает `HTTPСоединение`+`HTTPЗапрос` `POST /chat {message, user_id, attachments, context_size}` и парсит SSE (`answer`/`tool`/`done`) на сервере (`ИзвлечьОтветИзSSE`). Если `ВыполнятьВФоне` — уходит в `a1c_ЧатФоновыйВызов`.
- JS в `HTMLЧат` оставлен как fallback для старого SSE, но основной путь — BSL `ОтветHTML` через `ШаблонДиалога`. Открытие: **Все функции** → Обработки → `a1c_Чат`.

## Контур запуска

### Основной — бэкенд на Linux (VPS/сервер)

```bash
cp .env.example .env          # LLM_*, MCP_ONEC_URL=http://<1С-хост>/base
docker compose up -d postgres backend   # :8000, миграции сами
docker compose logs -f backend
# прокси рядом на Linux (8001):
pip install -r /path/to/1c_mcp/src/py_server/requirements.txt
python -m src.py_server http --port 8001 --onec-url http://<iis>/ka2test --onec-username agent --onec-password ...
# .env: ONEC_MODE=live  ONEC_MCP_URL=http://localhost:8001  # внутри compose http://mcp-proxy:8000
```

Требует сети Linux → Windows-VM (VPN/Tailscale/проброс IIS/SSH-туннель). Если сети нет — fallback ниже. В 1С поле «Бэкенд» → `http://<linux-хост>:8000`.

### Fallback — всё на Windows (без сети)

`docker compose up -d postgres` в Docker Desktop + `uv run uvicorn` и прокси на той же машине. «Бэкенд» → `http://localhost:8000`.

`ONEC_MODE`: `mock`/`live`. Смоук: `uv run python scripts/smoke_tools.py --live` (и `--replay`).

## Благодарности

- Роман Андриянов ([andromanpro](https://github.com/andromanpro)) — `КИИ_МаркдаунПарсерКлиентСервер` и `КИИ_ТестИИ` (MIT)
