#!/bin/sh
# Применяет миграции и запускает бота (schema-first старт в контейнере).
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting kwork_bot"
exec python -m main
