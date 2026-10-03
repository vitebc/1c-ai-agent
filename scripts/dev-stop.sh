#!/bin/bash
# Остановить dev окружение (prod не трогается)
set -e

cd "$(dirname "$0")/.."

echo "=== Остановка dev окружения ==="
docker compose -f docker-compose.dev.yml down

echo "✓ Dev окружение остановлено"
echo "  Prod остаётся работать на :8000"
