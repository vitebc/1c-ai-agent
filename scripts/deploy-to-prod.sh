#!/bin/bash
# Деплой отлаженного кода в prod
# Использовать ТОЛЬКО после успешных тестов на dev (:8001)
set -e

cd "$(dirname "$0")/.."

echo "=== ДЕПЛОЙ В PROD ==="
echo "Убедись, что код отлажен на dev (http://localhost:8001)"
read -p "Продолжить? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Отменено"
    exit 1
fi

echo ""
echo "Пересборка prod backend..."
docker compose build backend

echo ""
echo "Перезапуск prod контейнера..."
docker compose up -d backend

echo ""
echo "Ожидаю здоровье..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health | grep -q "ok"; then
        echo "✓ Prod backend обновлён на :8000"
        break
    fi
    sleep 2
done

echo ""
echo "=== Деплой завершён ==="
echo "Prod: http://localhost:8000"
echo "Dev:  http://localhost:8001 (не тронут)"
