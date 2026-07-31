FROM python:3.12-slim AS python-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


FROM node:20-slim AS frontend-builder

WORKDIR /build
COPY . .
RUN cd theme/static_src && npm ci && npm run build


FROM python:3.12-slim AS runtime

ARG RUANG_BUILD_REVISION=development
ARG RUANG_SOURCE_CODE_URL=https://github.com/unknownymouse/ruang

LABEL org.opencontainers.image.title="Ruang" \
      org.opencontainers.image.source="${RUANG_SOURCE_CODE_URL}" \
      org.opencontainers.image.revision="${RUANG_BUILD_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    RUANG_SOURCE_CODE_URL="${RUANG_SOURCE_CODE_URL}" \
    RUANG_SOURCE_CODE_REVISION="${RUANG_BUILD_REVISION}"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system ruang \
    && adduser --system --ingroup ruang --home /app ruang

COPY requirements.txt .
COPY --from=python-builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=ruang:ruang . .
COPY --from=frontend-builder --chown=ruang:ruang \
    /build/theme/static/css/dist/styles.css \
    /app/theme/static/css/dist/styles.css

RUN mkdir -p /app/media /app/staticfiles \
    && chown -R ruang:ruang /app/media /app/staticfiles

USER ruang

# Static collection deliberately uses base settings. Production settings are
# reserved for runtime and may enforce deployment-only security invariants.
RUN DJANGO_SETTINGS_MODULE=config.settings.base \
    SECRET_KEY=collectstatic-build-placeholder \
    DATABASE_URL=sqlite:////tmp/collectstatic.db \
    STORAGE_BACKEND=local \
    EMAIL_BACKEND_TYPE=console \
    python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:${PORT:-8000}/health/ || exit 1

CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --error-logfile -"]
