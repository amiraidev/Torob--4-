FROM node:22-alpine AS frontend
WORKDIR /web
COPY package*.json ./
RUN npm ci --no-fund --no-audit
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
# Production uses Django's full catalog; the static-demo snapshot stays in source only.
RUN npm run build && rm -f dist/data/catalog.json dist/data/catalog.json.gz

FROM python:3.12-slim AS catalog
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /opt/venv && pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY scripts ./scripts
COPY data ./data
# Data is prepared at build time. No AI credentials or external API calls here.
RUN python scripts/build_seed.py \
    && DJANGO_DEBUG=true LLM_ENABLED=false python backend/manage.py collectstatic --noinput

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    TOROB_IN_DOCKER=true \
    DJANGO_DEBUG=false \
    DJANGO_DB_PATH=/app/storage/db.sqlite3 \
    DJANGO_SECRET_KEY_FILE=/app/storage/django-secret-key \
    DJANGO_ALLOWED_HOSTS=torob-yar-v2.liara.run,torob-yar.liara.run,localhost,127.0.0.1,[::1] \
    DJANGO_CORS_ORIGINS=https://torob-yar-v2.liara.run,https://torob-yar.liara.run \
    DJANGO_CSRF_TRUSTED_ORIGINS=https://torob-yar-v2.liara.run,https://torob-yar.liara.run \
    TRUST_PROXY_HTTPS=true \
    SECURE_SSL_REDIRECT=true \
    PORT=8000
WORKDIR /app
COPY --from=catalog /opt/venv /opt/venv
COPY --from=catalog /app/backend ./backend
COPY --from=catalog /app/bootstrap ./bootstrap
COPY scripts ./scripts
COPY --from=frontend /web/dist ./dist
# Intentional private-file deployment: only LLM_* values are read from this file.
# It never enters the Node build or the public/static directory.
COPY .env ./config/runtime.env
RUN groupadd --gid 1001 appuser \
    && useradd --uid 1001 --gid 1001 --no-create-home appuser \
    && mkdir -p /app/storage \
    && chown -R appuser:appuser /app \
    && chmod 0400 /app/config/runtime.env \
    && chmod 0444 /app/bootstrap/catalog.sqlite3 /app/bootstrap/catalog.json
USER root
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD ["python", "/app/scripts/healthcheck.py"]
ENTRYPOINT ["python", "/app/scripts/container_start.py"]

