"""Agent memory service — FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import get_settings
from backend.redis_client import close_redis
from backend.routers import agents, memories, trust

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(agents.router)
app.include_router(memories.router)
app.include_router(trust.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
