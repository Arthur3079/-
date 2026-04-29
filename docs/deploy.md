# Deploy runbook (Combine)

Production deployment of the Combine stack — FastAPI backend (serving the
React SPA on `/app`) + Telethon worker + PostgreSQL — via Docker Compose.

## Prerequisites

- Docker 24+ with the `compose` plugin (`docker compose version`)
- A populated `.env` at the repo root (copy `.env.example` if present and fill
  in `DATABASE_URL`, `AUTH_JWT_SECRET`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
  etc.)

## Build & run

```bash
docker compose build
docker compose up -d
# First-time schema bootstrap:
docker compose exec backend alembic upgrade head
```

The SPA is baked into the `backend` image at build time (Node stage runs
`npm ci && npm run build` and copies `frontend/dist/` into
`sonya_web/static/spa/`). No volume mount is needed for the frontend.

## Verify

- Backend API:
  ```bash
  curl -sSf http://localhost:8000/api/combine/analytics/summary
  ```
  Expect `200 OK` and a JSON body matching `OverallSummary`.

- SPA:
  ```bash
  curl -sSf http://localhost:8000/app/ | head -5
  ```
  Expect `200 OK` and the React `index.html`.

- Worker: `docker compose logs -f worker` — should log the worker starting
  with registered plugins `['parser', 'commenting', 'reactions', 'warming']`.

## Logs

```bash
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f db
```

## Stop / restart

```bash
docker compose down           # stop and remove containers
docker compose down -v        # also drop the postgres volume
docker compose restart worker # restart just the worker
```

## Local iteration (without Docker)

```bash
# Backend
uvicorn sonya_web.app:app --reload --port 8000

# Worker
python -m scripts.run_worker

# Frontend (dev server with HMR)
cd frontend && npm run dev
```

When running the backend locally, the `/app` SPA mount is skipped unless
`sonya_web/static/spa/index.html` exists. Build the SPA with
`cd frontend && npm run build` and copy `dist/*` into
`sonya_web/static/spa/` to exercise the mount locally.
