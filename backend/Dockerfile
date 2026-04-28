FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Use shell form so $PORT is expanded at runtime (Railway injects PORT).
# Falls back to 8000 for local docker-compose.
CMD sh -c "echo '=== Starting. PORT='$PORT && python manage.py migrate && echo '=== Migrations OK' && (python manage.py seed_data || echo '=== Seed failed, continuing') && echo '=== Starting gunicorn on port '${PORT:-8000} && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60"
