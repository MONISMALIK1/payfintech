#!/bin/sh
set -e

PORT="${PORT:-8080}"

echo ">>> Running migrations..."
python manage.py migrate --noinput
echo ">>> Migrations done"

echo ">>> Starting Celery worker+beat in background..."
celery -A config worker --beat \
    --loglevel=info \
    --concurrency=2 \
    --schedule /tmp/celerybeat-schedule \
    &

echo ">>> Starting gunicorn on 0.0.0.0:$PORT"
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:$PORT" \
    --workers 2 \
    --timeout 60 \
    --log-level info \
    --access-logfile - \
    --error-logfile -
