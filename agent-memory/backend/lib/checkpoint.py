"""Crash recovery checkpointing via Redis (no TTL — persists until cleared)."""

from __future__ import annotations

import json
from typing import Any

_KEY_PREFIX = "checkpoint:"


def _redis_key(task_name: str) -> str:
    return f"{_KEY_PREFIX}{task_name}"


async def save_checkpoint(redis: Any, task_name: str, state: dict[str, Any]) -> None:
    await redis.set(_redis_key(task_name), json.dumps(state, default=str))


async def load_checkpoint(redis: Any, task_name: str) -> dict[str, Any] | None:
    raw = await redis.get(_redis_key(task_name))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def clear_checkpoint(redis: Any, task_name: str) -> None:
    await redis.delete(_redis_key(task_name))
