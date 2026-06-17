# BENE Temporal worker image.
# Build context is the repo root: docker compose handles this with `context: ..`.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first to maximize layer cache reuse.
COPY pyproject.toml README.md ./
COPY bene ./bene

RUN pip install --upgrade pip \
    && pip install '.[temporal]'

# Healthcheck: process must respond on Temporal task queue (best-effort)
# A stricter check would query Temporal directly via tctl/temporal CLI.
CMD ["bene", "temporal", "worker", "--address", "temporal:7233", "--queue", "bene-main", "--postgres-dsn", "YOUR_DSN_HERE"]
