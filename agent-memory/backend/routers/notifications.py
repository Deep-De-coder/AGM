"""Redis-backed notification feed (list key ``notifications``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from backend.notifications import get_notifications, mark_read, unread_count
from backend.redis_client import get_redis
from backend.schemas import UnreadCountResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _normalize_notification(d: dict[str, Any]) -> dict[str, Any]:
    """Align Redis JSON with dashboard (created_at, is_read, read_at)."""
    out: dict[str, Any] = {k: v for k, v in d.items() if k != "read"}
    ts = d.get("timestamp") if d.get("timestamp") is not None else d.get("created_at")
    if ts is not None:
        if hasattr(ts, "isoformat"):
            out["created_at"] = ts.isoformat()
        else:
            out["created_at"] = str(ts)
    elif "created_at" not in out:
        out["created_at"] = ""
    raw_read = d.get("read", False)
    out["is_read"] = bool(raw_read)
    out["read_at"] = d.get("read_at") if raw_read else None
    return out


@router.get("")
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    redis = await get_redis()
    raw = await get_notifications(redis, limit=limit)
    return [_normalize_notification(dict(x)) for x in raw]


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count() -> UnreadCountResponse:
    redis = await get_redis()
    n = await unread_count(redis)
    return UnreadCountResponse(count=n)


@router.post("/{notification_id}/read")
async def mark_notification_read(notification_id: str) -> dict[str, bool]:
    redis = await get_redis()
    await mark_read(notification_id, redis)
    return {"ok": True}
