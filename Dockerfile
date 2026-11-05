# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS basis

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Statische Dateien zur Build-Zeit sammeln (nur Platzhalter-Geheimnisse, nicht zur Laufzeit genutzt)
RUN DJANGO_SECRET_KEY=build-only COCKPIT_FERNET_KEYS=YnVpbGQtb25seS1ub3QtYS1yZWFsLWtleS0xMjM0NTY= \
    python manage.py collectstatic --noinput

# Ohne Root laufen; Dateiablage außerhalb des Webroots
RUN groupadd --system --gid 10001 cockpit \
    && useradd --system --uid 10001 --gid cockpit --home-dir /app --shell /usr/sbin/nologin cockpit \
    && mkdir -p /data/dateien \
    && chown -R cockpit:cockpit /data
ENV COCKPIT_DATEIABLAGE=/data/dateien
USER 10001:10001

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
