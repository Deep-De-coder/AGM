"""Content-addressed memory integrity (SHA256 over canonical fields)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import log_memory_event
from backend.models import Memory
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import get_redis

HASH_FIELDS = ("content", "agent_id", "session_id", "source_type", "source_identifier")


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def compute_content_hash(memory_data: dict[str, Any]) -> str:
    """Deterministic SHA256 over pipe-separated canonical fields + created_at."""
    parts: list[str] = []
    for k in HASH_FIELDS:
        v = memory_data.get(k)
        if v is None:
            parts.append("")
        elif hasattr(v, "hex"):  # UUID
            parts.append(str(v))
        else:
            parts.append(str(v))
    created = memory_data.get("created_at")
    if isinstance(created, datetime):
        parts.append(_iso(created))
    else:
        parts.append(str(created or ""))
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize_for_hash(memory: Memory) -> dict[str, Any]:
    return {
        "content": memory.content,
        "agent_id": memory.agent_id,
        "session_id": memory.session_id,
        "source_type": memory.source_type,
        "source_identifier": memory.source_identifier,
        "created_at": memory.created_at,
    }


def verify_content_hash(memory: Memory) -> bool:
    if not memory.content_hash:
        return True
    recomputed = compute_content_hash(_serialize_for_hash(memory))
    return recomputed == memory.content_hash


async def verify_memory_integrity(
    memory: Memory,
    db: AsyncSession,
    redis_client: Redis | None,
) -> dict[str, Any]:
    """Verify DB row against stored hash; flag + notify on mismatch."""
    now = datetime.now(timezone.utc)
    valid = verify_content_hash(memory)
    recomputed = compute_content_hash(_serialize_for_hash(memory))
    stored = memory.content_hash
    memory.content_hash_verified_at = now

    if not valid and stored:
        memory.content_hash_valid = False
        memory.is_flagged = True
        memory.flag_reason = (
            "INTEGRITY VIOLATION: content_hash mismatch — "
            "memory may have been tampered with at storage level"
        )
        await log_memory_event(
            db,
            memory_id=memory.id,
            event_type="anomaly_flagged",
            performed_by_agent_id=None,
            event_metadata={
                "type": "content_hash_mismatch",
                "stored_hash": stored,
                "computed_hash": recomputed,
            },
        )
        try:
            r = redis_client or await get_redis()
            await push_notification(
                NotificationEvent(
                    id=str(uuid.uuid4()),
                    type="rule_violation",
                    severity="CRITICAL",
                    title="Integrity violation",
                    message=(
                        f"INTEGRITY VIOLATION: Memory {memory.id} content hash "
                        "does not match stored hash. Storage-level tampering detected."
                    ),
                    memory_id=str(memory.id),
                    agent_id=str(memory.agent_id),
                    rule_name="INTEGRITY",
                    timestamp=now,
                    read=False,
                ),
                r,
            )
        except Exception:
            pass

    redis_client = redis_client or await get_redis()
    _ = redis_client  # optional side effects reserved
    return {
        "valid": valid,
        "stored_hash": stored,
        "computed_hash": recomputed,
        "verified_at": now.isoformat(),
    }
