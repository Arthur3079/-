# syntax=docker/dockerfile:1.7

# Stage 1: build the React SPA.
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI runtime, serves the API and the built SPA on /app.
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy sources first so `pip install '.[web]'` can resolve the project
# (setuptools needs the package layout present). requirements.txt acts
# as a pin file for humans; pyproject.toml is the source of truth for
# the runtime image (core deps + `web` extras for FastAPI / uvicorn).
COPY pyproject.toml requirements.txt README.md ./
COPY sonya ./sonya
COPY sonya_web ./sonya_web
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --upgrade pip \
    && pip install --no-cache-dir ".[web]"

# Copy the SPA bundle produced in stage 1 into the static mount point.
COPY --from=frontend-build /app/frontend/dist ./sonya_web/static/spa

EXPOSE 8000
CMD ["uvicorn", "sonya_web.app:app", "--host", "0.0.0.0", "--port", "8000"]
