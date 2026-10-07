#!/usr/bin/env bash
# Накатка prod: build образа из main + синхронизация runtime-файлов в prod-директорию.
# Prod — /home/test/.config/ai-1c-server/1c-chat (не git): только backend + postgres.
#
# Использование:
#   scripts/deploy_prod.sh          # из main после git push origin main
#
# Не трогает .env и БД prod. Откат: docker compose up -d --no-build в старой копии
# (обратный rsync не нужен — runtime-файлы пересинхронизируются при следующем deploy).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROD="${PROD_DIR:-/home/test/.config/ai-1c-server/1c-chat}"

if [ ! -d "$PROD" ]; then
  echo "Prod-директория не найдена: $PROD (переопределите PROD_DIR)" >&2
  exit 1
fi

# Только из main — dev-правки в prod не накатываются.
BRANCH="$(git -C "$REPO" branch --show-current)"
if [ "$BRANCH" != "main" ]; then
  echo "Deploy только из ветки main (сейчас: $BRANCH). git checkout main && git pull origin main" >&2
  exit 1
fi

echo "== Build образа из main (no-cache: src/ обязана быть свежей) =="
# Dev-образ собирается как 1c-ai-agent-backend:dev, prod-compose ждёт :latest —
# без тега prod молча поднимет старый образ (проверено: дубль кода не накатывался).
(cd "$REPO" && docker compose build --no-cache backend && \
  docker tag "${BACKEND_IMAGE:-1c-ai-agent-backend}:dev" "${BACKEND_IMAGE:-1c-ai-agent-backend}:latest")

echo "== Синхронизация runtime-файлов в $PROD =="
# Без --delete: существующие файлы в prod НЕ затираются, локальные правки и
# новые файлы (напр. скилы, сгенерированные через чат) переживают деплой.
# Git — источник правды для ОБНОВЛЕНИЯ, но не для удаления.
# Чтобы удалить агента/скилл/паттерн из prod: удалить из git И вручную rm -r в prod.
for d in agents skills patterns; do
  mkdir -p "$PROD/backend/$d"
  rsync -a "$REPO/backend/$d/" "$PROD/backend/$d/"
done
# Одиночные файлы — без --delete (bases.conf может быть отредактирован на хосте).
cp "$REPO/backend/bases.conf" "$PROD/backend/bases.conf"
cp "$REPO/backend/Dockerfile" "$PROD/backend/Dockerfile"
mkdir -p "$PROD/backend/alembic"
rsync -a --delete "$REPO/backend/alembic/" "$PROD/backend/alembic/"
cp "$REPO/backend/alembic.ini" "$PROD/backend/alembic.ini"

echo "== Перезапуск backend (force-recreate: гарантируем новый образ) =="
(cd "$PROD" && docker compose up -d --force-recreate backend)

echo "== Проверка =="
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "OK: $(curl -s http://localhost:8000/health)"
    exit 0
  fi
  sleep 3
done
echo "FAIL: /health не отвечает через 90с. (cd $PROD && docker compose logs backend)" >&2
exit 1
