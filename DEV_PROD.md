# Dev / Prod окружения

Полное разделение dev и prod для безопасной разработки:
- **Dev** — для отладки, можно ломать, чистить БД, экспериментировать
- **Prod** — боевой, не трогается до явного деплоя

## Архитектура

```
DEV:
  ai-1c-server-dev (:9225) → backend-dev (:8001) → postgres-dev (:5434)
  
PROD:
  ai-1c-server-prod (:9224) → backend-prod (:8000) → postgres-prod (:5432)
```

## Быстрый старт

### Поднять dev окружение (бэкенд + PostgreSQL)

```bash
cd /home/test/project/1c-ai-agent
./scripts/dev-start.sh
```

### Поднять dev админку (ai-1c-server)

```bash
cd /home/test/project/ai-1c-server
./scripts/start-dev.sh
```

### Проверить, что всё работает

```bash
# Dev backend
curl http://localhost:8001/health

# Dev admin
curl http://localhost:9225/health

# Prod (не должен быть тронут)
curl http://localhost:8000/health
curl http://localhost:9224/health
```

## Цикл разработки

### 1. Внести изменения в код бэкенда

```bash
cd /home/test/project/1c-ai-agent
# Редактировать backend/src/**
```

### 2. Пересобрать и перезапустить dev

```bash
./scripts/dev-build.sh
```

### 3. Тестировать на dev

```bash
# Отправить тестовый запрос в dev
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"тест","user_id":"test-u1"}'

# Проверить статистику через dev админку
# http://localhost:9225 → Статистика
```

### 4. После успешных тестов — деплой в prod

```bash
./scripts/deploy-to-prod.sh
```

Скрипт спросит подтверждение, пересоберёт и перезапустит prod контейнер.

## Остановка dev

```bash
# Остановить dev бэкенд + PostgreSQL
cd /home/test/project/1c-ai-agent
./scripts/dev-stop.sh

# Остановить dev админку
cd /home/test/project/ai-1c-server
./scripts/stop-dev.sh
```

Prod продолжает работать.

## Чистка dev БД

```bash
cd /home/test/project/1c-ai-agent
docker compose -f docker-compose.dev.yml exec -T postgres-dev \
  psql -U agent -d agentdb -c "TRUNCATE chat_requests;"
```

Prod БД не трогается.

## Переменные окружения

### Dev (`.env.dev`)

- `BACKEND_DEV_PORT=8001` — порт dev бэкенда
- `POSTGRES_DEV_PORT=5434` — порт dev PostgreSQL
- `AGENT_ENV=dev` — флаг для ai-1c-server (читает `.env.dev`)

### Prod (`.env`)

- `BACKEND_PORT=8000` — порт prod бэкенда
- `POSTGRES_PORT=5432` — порт prod PostgreSQL
- `ENVIRONMENT=prod` — флаг окружения

## Файлы

### 1c-ai-agent

- `docker-compose.yml` — prod окружение
- `docker-compose.dev.yml` — dev окружение
- `.env` — prod конфигурация
- `.env.dev` — dev конфигурация
- `scripts/dev-start.sh` — запуск dev
- `scripts/dev-stop.sh` — остановка dev
- `scripts/dev-build.sh` — пересборка dev
- `scripts/deploy-to-prod.sh` — деплой в prod

### ai-1c-server

- `scripts/start-dev.sh` — запуск dev админки (порт 9225)
- `scripts/stop-dev.sh` — остановка dev админки
- `data-dev/` — dev БД SQLite (отдельная от `data/`)

## Важно

1. **Никогда не редактируй prod во время dev-работы.** Все изменения → dev → тесты → деплой.
2. **Dev БД можно чистить свободно** (`TRUNCATE`, `DROP TABLE`). Prod — нет.
3. **Порты не пересекаются:** dev (8001, 5434, 9225), prod (8000, 5432, 9224).
4. **Деплой только после успешных тестов на dev.** Скрипт `deploy-to-prod.sh` спросит подтверждение.
