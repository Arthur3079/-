FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY sonya ./sonya
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --upgrade pip \
    && pip wheel --no-deps --wheel-dir=/wheels . \
    && pip install --prefix=/install .


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.11/site-packages"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 1000 sonya

WORKDIR /app

COPY --from=builder /install /install
COPY --from=builder /app /app
COPY knowledge ./knowledge

RUN mkdir -p /app/logs /app/data \
    && chown -R sonya:sonya /app

USER sonya

ENV LOG_DIR=/app/logs \
    DATABASE_URL=sqlite+aiosqlite:////app/data/sonya.db

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command runs the userbot. The compose file overrides this for the
# payment bot service.
CMD ["python", "-m", "sonya.main"]
