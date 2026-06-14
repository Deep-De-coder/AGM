"""Idempotency key support for POST /memories (dedup within 1 hour)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

IDEMPOTENCY_TTL = 3600

_KEY_PREFIX = "idempotency:"


def _redis_key(idempotency_key: str) -> str:
    return f"{_KEY_PREFIX}{idempotency_key}"


def compute_content_idempotency_key(
    agent_id: str,
    content: str,
    session_id: str | None,
    source_type: str,
    source_identifier: str = "",
    safety_context: dict[str, Any] | None = None,
) -> str:
    """SHA256 of pipe-separated fields — identical writes from the same agent = same key."""
    ctx_hash = hashlib.sha256(
        json.dumps(safety_context or {}, sort_keys=True).encode()
    ).hexdigest()[:16]
    raw = f"{agent_id}|{content}|{session_id or ''}|{source_type}|{source_identifier}|{ctx_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def check_idempotency(redis: Any, idempotency_key: str) -> dict[str, Any] | None:
    raw = await redis.get(_redis_key(idempotency_key))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def store_idempotency(
    redis: Any, idempotency_key: str, response: dict[str, Any]
) -> None:
    await redis.set(
        _redis_key(idempotency_key),
        json.dumps(response, default=str),
        ex=IDEMPOTENCY_TTL,
    )
