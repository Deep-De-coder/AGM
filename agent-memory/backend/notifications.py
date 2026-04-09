"""In-memory asyncio queue + Redis-backed notification feed."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

NOTIFICATIONS_LIST_KEY = "notifications"
NOTIFICATIONS_READ_SET_KEY = "notifications:read"
_MAX_LIST = 100


@dataclass
class NotificationEvent:
    id: str
    type: str
    severity: str
    title: str
    message: str
    memory_id: str
    agent_id: str
    rule_name: str
    timestamp: datetime
    read: bool

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


_notification_queue: asyncio.Queue[NotificationEvent] = asyncio.Queue()


async def push_notification(event: NotificationEvent, redis: Redis) -> None:
    """Enqueue in-process and persist to Redis list (newest first, capped)."""
    try:
        _notification_queue.put_nowait(event)
    except asyncio.QueueFull:
        pass
    blob = json.dumps(event.to_json(), default=str)
    await redis.lpush(NOTIFICATIONS_LIST_KEY, blob)
    await redis.ltrim(NOTIFICATIONS_LIST_KEY, 0, _MAX_LIST - 1)


async def get_notifications(redis: Redis, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent notifications merged with read state from Redis."""
    raw = await redis.lrange(NOTIFICATIONS_LIST_KEY, 0, max(0, limit - 1))
    read_ids = await redis.smembers(NOTIFICATIONS_READ_SET_KEY)
    read_set = set(read_ids or [])
    out: list[dict[str, Any]] = []
    for item in raw:
        try:
            d = json.loads(item)
        except json.JSONDecodeError:
            continue
        nid = d.get("id", "")
        d["read"] = nid in read_set
        out.append(d)
    return out


async def mark_read(notification_id: str, redis: Redis) -> None:
    await redis.sadd(NOTIFICATIONS_READ_SET_KEY, notification_id)


async def unread_count(redis: Redis) -> int:
    raw = await redis.lrange(NOTIFICATIONS_LIST_KEY, 0, _MAX_LIST - 1)
    read_ids = await redis.smembers(NOTIFICATIONS_READ_SET_KEY)
    read_set = set(read_ids or [])
    n = 0
    for item in raw:
        try:
            d = json.loads(item)
        except json.JSONDecodeError:
            continue
        nid = d.get("id", "")
        if nid and nid not in read_set:
            n += 1
    return n
