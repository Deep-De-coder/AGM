"""Redis-backed security and trust notification feed."""

from fastapi import APIRouter, Query

from backend.notifications import get_notifications
from backend.redis_client import get_redis

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    redis = await get_redis()
    return await get_notifications(redis, limit=limit)
