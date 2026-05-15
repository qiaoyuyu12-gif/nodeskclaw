FROM python:3.12-slim

ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""
ARG APT_MIRROR=""

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    UV_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi && \
    pip install --no-cache-dir uv && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker.io docker-compose && \
    rm -rf /var/lib/apt/lists/*

COPY nodeskclaw-backend/pyproject.toml nodeskclaw-backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY nodeskclaw-backend/ .
COPY openclaw-channel-nodeskclaw/ ./openclaw-channel-nodeskclaw/
COPY openclaw-channel-dingtalk/ ./openclaw-channel-dingtalk/
COPY features.yaml ./features.yaml

RUN mkdir -p /app/data

COPY nodeskclaw-backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV NODESKCLAW_ROOT=/app
ENV PYTHONUNBUFFERED=1
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["/bin/sh", "-c", ".venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"]
