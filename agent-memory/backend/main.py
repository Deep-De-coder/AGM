"""Agent memory service — FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.database import engine
from backend.redis_client import close_redis
from backend.routers import (
    admin,
    agents,
    graph,
    memories,
    notifications,
    stats,
    trust,
    violations,
)
from backend.trust_engine import start_trust_background_task, stop_trust_background_task

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_trust_background_task()
    yield
    await stop_trust_background_task()
    await close_redis()
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
app.include_router(stats.router)
app.include_router(graph.router)
app.include_router(violations.router)
app.include_router(admin.router)
app.include_router(notifications.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
