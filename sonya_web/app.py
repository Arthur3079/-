"""FastAPI веб-панель для Sonya.

Запуск локально::

    uvicorn sonya_web.app:app --reload --port 8000

Затем открыть http://localhost:8000.

Никакой авторизации — это локальный MVP. Не выставлять наружу.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sonya_web.routers import (
    admin_actions,
    clients,
    combine_accounts,
    combine_proxies,
    dashboard,
    events_stream,
    funnel,
    llm,
    safety,
    sales,
    scheduler,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Lifecycle hook — место под прогрев кэшей в будущем."""
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sonya Admin",
        description="Локальная веб-панель для наблюдения и управления Sonya.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # На локалке CORS не нужен, но если фронт будет отдельно — пригодится.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
    app.include_router(clients.router, prefix="/api", tags=["clients"])
    app.include_router(funnel.router, prefix="/api", tags=["funnel"])
    app.include_router(safety.router, prefix="/api", tags=["safety"])
    app.include_router(scheduler.router, prefix="/api", tags=["scheduler"])
    app.include_router(events_stream.router, prefix="/api", tags=["events"])
    app.include_router(sales.router, prefix="/api", tags=["sales"])
    app.include_router(llm.router, prefix="/api", tags=["llm"])
    app.include_router(admin_actions.router, prefix="/api", tags=["admin"])
    app.include_router(combine_proxies.router, prefix="/api")
    app.include_router(combine_accounts.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
