# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 1000 regate

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=regate:regate . .
# collectstatic needs settings to load; the key is thrown away with this layer.
RUN DEBUG=false SECRET_KEY=build-only-not-secret-0123456789abcdefghijklmnopqrstuvwxyz \
    python manage.py collectstatic --noinput \
 && mkdir -p /app/media && chown regate:regate /app/media

USER regate
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/').status == 200 else 1)"

# Migrations run before the server so a deploy never serves an unmigrated schema.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY:-3} --timeout 60 --access-logfile -"]
