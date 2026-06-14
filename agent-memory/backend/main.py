"""Agent memory service — FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import redis_client
from backend.config import get_settings
from backend.database import engine
from backend.routers import (
    admin,
    agents,
    graph,
    memories,
    notifications,
    project,
    stats,
    trust,
    violations,
)
from backend.trust_engine import start_trust_background_task, stop_trust_background_task

settings = get_settings()
_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    redis = await redis_client.get_redis()

    # Informational: warn if stale checkpoints exist (indicates a previous crash)
    from backend.lib.checkpoint import load_checkpoint

    for task_name in ("trust_decay", "dca_scan"):
        cp = await load_checkpoint(redis, task_name)
        if cp:
            _logger.warning(
                "Stale checkpoint found for '%s' on startup: %s — "
                "previous run may have crashed; background task will resume.",
                task_name,
                cp,
            )

    start_trust_background_task()
    yield
    await stop_trust_background_task()
    await redis_client.close_redis()
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(memories.router)
app.include_router(trust.router)
app.include_router(trust.alias_router)
app.include_router(stats.router)
app.include_router(graph.router)
app.include_router(violations.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(project.router, prefix="/project", tags=["Project Graph"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
