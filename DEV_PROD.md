# Dev / Prod окружения

Полная изоляция: dev-сервер для разработки и тестирования, prod-сервер для пользователей.
Правки в dev не затрагивают prod; накатка только после успешного тестирования.

## Архитектура

```
PROD (ветка main):
  /home/test/project/1c-ai-agent/
    backend (:8000) → postgres (:5432, volume postgres-data)

DEV (ветка dev, git worktree):
  /home/test/project/1c-ai-agent-dev/
    backend (:8001) → postgres (:5435, volume dev-postgres-data)
```

LLM, базы 1С, агрегатор — общие для обоих окружений.

## Различия

| Параметр | Prod (`main`) | Dev (`dev`, worktree) |
|---|---|---|
| Путь | `/home/test/project/1c-ai-agent` | `/home/test/project/1c-ai-agent-dev` |
| Бэкенд | `:8000` | `:8001` |
| Postgres | `:5432`, volume `postgres-data` | `:5435`, volume `dev-postgres-data` |
| JWT_SECRET | задан (per-user RLS) | пусто (Basic auth под `agent`) |
| Эмбеддинги | `tei` (профиль rag) | `fake` |
| LLM / базы 1С / агрегатор | те же | те же |

## Рабочий цикл

```bash
# 1. Разработка в dev
cd /home/test/project/1c-ai-agent-dev
# правки: backend/src/**, agents/, skills/, patterns/...
docker compose up -d --build backend    # :8001, тестируешь
git add -A && git commit -m "feat: ..." && git push origin dev

# 2. Накатка в prod (после проверки)
cd /home/test/project/1c-ai-agent
git merge dev && git push origin main
docker compose up -d --build backend    # :8000, пользователи получают фичу
```

## Создание dev-worktree (один раз)

```bash
cd /home/test/project/1c-ai-agent
git checkout -b dev && git push origin dev
git worktree add ../1c-ai-agent-dev dev
cd ../1c-ai-agent-dev
cp .env.dev .env
# В docker-compose.yml: volume postgres-data → dev-postgres-data
docker compose up -d postgres backend
```

## Проверка

```bash
# Prod (не должен быть тронут)
curl http://localhost:8000/health

# Dev
curl http://localhost:8001/health
```

## Чистка dev БД

```bash
cd /home/test/project/1c-ai-agent-dev
docker compose exec -T postgres \
  psql -U agent -d agentdb -c "TRUNCATE chat_requests;"
```

Prod БД не трогается.

## Важно

1. **Никогда не редактируй prod во время dev-работы.** Все изменения → dev → тесты → мерж в main.
2. **Dev БД можно чистить свободно** (`TRUNCATE`, `DROP TABLE`). Prod — нет.
3. **Порты не пересекаются:** dev (8001, 5435), prod (8000, 5432).
4. **Накатка только после успешных тестов на dev.**
