#!/bin/bash
# Поднять dev окружение (backend-dev + postgres-dev)
set -e

cd "$(dirname "$0")/.."

echo "=== Запуск dev окружения ==="
docker compose -f docker-compose.dev.yml up -d

echo ""
echo "Ожидаю здоровье..."
for i in {1..30}; do
    if curl -s http://localhost:8001/health | grep -q "ok"; then
        echo "✓ Dev backend запущен на :8001"
        break
    fi
    sleep 2
done

echo ""
echo "Dev окружение:"
echo "  Backend:  http://localhost:8001"
echo "  Postgres: localhost:5434 (agentdb_dev)"
echo ""
echo "Prod остаётся нетронутым на :8000"
