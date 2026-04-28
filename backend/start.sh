#!/bin/sh
set -e

PORT="${PORT:-8000}"
echo ">>> PORT=$PORT"
echo ">>> Running migrations..."
python manage.py migrate --noinput
echo ">>> Migrations complete. Starting gunicorn on 0.0.0.0:$PORT"
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:$PORT" \
    --workers 2 \
    --timeout 60 \
    --log-level info \
    --access-logfile - \
    --error-logfile -
