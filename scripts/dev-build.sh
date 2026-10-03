#!/bin/bash
# Пересобрать dev backend после изменений кода
set -e

cd "$(dirname "$0")/.."

echo "=== Пересборка dev backend ==="
docker compose -f docker-compose.dev.yml build backend-dev

echo ""
echo "Перезапуск контейнера..."
docker compose -f docker-compose.dev.yml up -d backend-dev

echo ""
echo "Ожидаю здоровье..."
for i in {1..30}; do
    if curl -s http://localhost:8001/health | grep -q "ok"; then
        echo "✓ Dev backend пересобран и запущен на :8001"
        break
    fi
    sleep 2
done
