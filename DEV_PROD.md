# Dev / Prod окружения

Полная изоляция: main — разработка и тесты, prod — только запуск для пользователей.
Prod — отдельная директория **вне git**, в ней только то, что нужно для запуска бэкенда.
Накатка только после успешных тестов на main.

## Архитектура

```
MAIN (ветка main, разработка + тесты):
  /home/test/project/1c-ai-agent/
    backend (:8001, dev-конфиг) → postgres (:5435, volume dev-postgres-data)

PROD (не git, только запуск):
  /home/test/.config/ai-1c-server/1c-chat/
    backend (:8000) → postgres (:5432, volume 1c-chat_postgres-data)
```

LLM, базы 1С, агрегатор — общие для обоих окружений.

## Различия

| Параметр | Main (dev-конфиг) | Prod |
|---|---|---|
| Путь | `/home/test/project/1c-ai-agent` | `/home/test/.config/ai-1c-server/1c-chat` |
| Git | да (ветка `main`) | нет — только runtime-файлы |
| Бэкенд | `:8001` | `:8000` |
| Postgres | `:5435`, volume `dev-postgres-data` | `:5432`, volume `1c-chat_postgres-data` |
| JWT_SECRET | пусто (Basic auth под `agent`) | задан (per-user RLS) |
| Эмбеддинги | `fake` | `tei` (при необходимости, отдельный compose-файл) |

## Состав prod-директории

```
/home/test/.config/ai-1c-server/1c-chat/
├── .env                    # реальный prod .env (секреты; deploy не трогает)
├── docker-compose.yml      # только backend + postgres
├── backend/
│   ├── Dockerfile          # для пересборки при накатке
│   ├── agents/, skills/, patterns/   # runtime-конфиги, :ro mount, hot-reload
│   ├── bases.conf          # мапа баз ONEC_BASES (hot-reload по mtime)
│   └── alembic/ + alembic.ini        # миграции: контейнер сам гоняет upgrade head на старте
└── infra/postgres/init.sql
```

## Рабочий цикл

```bash
# 1. Разработка и тесты в main (dev-конфиг :8001)
cd /home/test/project/1c-ai-agent
docker compose up -d --build backend    # :8001, тестируешь
git add -A && git commit -m "feat: ..." && git push origin main

# 2. Накатка в prod (одной командой)
scripts/deploy_prod.sh
#   = build образа из main + rsync runtime-файлов в prod-директорию
#     + docker compose up -d backend (:8000) + проверка /health
```

`deploy_prod.sh` отказывается работать не из ветки `main`. `.env` и БД prod не трогает.

## Откат

Обратный deploy (git revert/checkout в main → `scripts/deploy_prod.sh`) или,
пока не пересобран образ, — ручной: вернуть runtime-файлы и
`(cd /home/test/.config/ai-1c-server/1c-chat && docker compose up -d --no-build backend)`.

## Проверка

```bash
# Main (dev-конфиг)
curl http://localhost:8001/health

# Prod
curl http://localhost:8000/health
```

## Чистка dev БД

```bash
cd /home/test/project/1c-ai-agent
docker compose exec -T postgres \
  psql -U agent -d agentdb -c "TRUNCATE chat_requests;"
```

Prod БД не трогается.

## Важно

1. **Main — и разработка, и тесты.** Правки в prod-директории руками — только
   `bases.conf` (hot-reload) и `.env`; всё остальное перезапишет deploy.
2. **Dev БД можно чистить свободно** (`TRUNCATE`, `DROP TABLE`). Prod — нет.
3. **Порты не пересекаются:** main (8001, 5435), prod (8000, 5432).
4. **Накатка только после успешных тестов на main.**
