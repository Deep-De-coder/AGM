"""Reconsolidation window: Redis locks + snapshots around memory retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import log_memory_event
from backend.models import Memory
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import get_redis, ns_key

LOCK_TTL_SECONDS = 30
SNAPSHOT_TTL_SECONDS = 300
LOCK_ACQUIRE_TIMEOUT_SECONDS = 5.0

SNAPSHOT_PREFIX = "reconsolidation:snapshot:"
LOCK_PREFIX = "reconsolidation:lock:"

logger = logging.getLogger(__name__)


def _serialize_memory_row(memory: Memory) -> dict[str, Any]:
    return {
        "id": str(memory.id),
        "content": memory.content,
        "trust_score": memory.trust_score,
        "is_flagged": memory.is_flagged,
        "flag_reason": memory.flag_reason,
        "memory_state": memory.memory_state,
        "updated_at": (
            memory.updated_at.isoformat()
            if memory.updated_at
            else datetime.now(timezone.utc).isoformat()
        ),
    }


def _hash_payload(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReconsolidationGuard:
    def __init__(self, redis_client: Redis | None = None):
        self._redis = redis_client

    async def _r(self) -> Redis:
        if self._redis is not None:
            return self._redis
        return await get_redis()

    async def acquire_lock(self, memory_id: str) -> bool:
        r = await self._r()
        key = ns_key(f"{LOCK_PREFIX}{memory_id}")
        val = f"{datetime.now(timezone.utc).timestamp()}:{secrets.token_hex(4)}"
        try:
            ok = await r.set(key, val, nx=True, ex=LOCK_TTL_SECONDS)
        except TypeError:
            if await r.get(key) is not None:
                return False
            await r.set(key, val, ex=LOCK_TTL_SECONDS)
            ok = True
        return bool(ok)

    async def release_lock(self, memory_id: str) -> None:
        try:
            r = await self._r()
            await r.delete(ns_key(f"{LOCK_PREFIX}{memory_id}"))
        except Exception:
            logger.debug("release_lock failed for %s", memory_id)

    async def take_snapshot(self, memory_id: str, memory: Memory) -> str:
        r = await self._r()
        data = _serialize_memory_row(memory)
        snap_hash = _hash_payload(data)
        payload = json.dumps(
            {
                "snapshot_hash": snap_hash,
                "snapshot_data": data,
                "taken_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        await r.set(
            ns_key(f"{SNAPSHOT_PREFIX}{memory_id}"),
            payload,
            ex=SNAPSHOT_TTL_SECONDS,
        )
        return snap_hash

    async def verify_snapshot(
        self, memory_id: str, current_memory: Memory, db: AsyncSession
    ) -> bool:
        r = await self._r()
        raw = await r.get(ns_key(f"{SNAPSHOT_PREFIX}{memory_id}"))
        if not raw:
            return True
        try:
            blob = json.loads(raw)
            orig_hash = blob.get("snapshot_hash")
        except (json.JSONDecodeError, TypeError):
            return True
        cur = _serialize_memory_row(current_memory)
        new_hash = _hash_payload(cur)
        if new_hash == orig_hash:
            return True
        old_data = blob.get("snapshot_data") or {}
        fields_changed = [k for k in old_data if old_data.get(k) != cur.get(k)]
        await log_memory_event(
            db,
            memory_id=current_memory.id,
            event_type="anomaly_flagged",
            performed_by_agent_id=None,
            event_metadata={
                "type": "reconsolidation_corruption",
                "snapshot_hash": orig_hash,
                "current_hash": new_hash,
                "fields_changed": fields_changed,
            },
        )
        try:
            await push_notification(
                NotificationEvent(
                    id=str(uuid.uuid4()),
                    type="rule_violation",
                    severity="HIGH",
                    title="Reconsolidation alert",
                    message=(
                        f"RECONSOLIDATION ALERT: Memory {memory_id} was modified "
                        "during retrieval window. Possible concurrent poisoning."
                    ),
                    memory_id=str(current_memory.id),
                    agent_id=str(current_memory.agent_id),
                    rule_name="RECONSOLIDATION",
                    timestamp=datetime.now(timezone.utc),
                    read=False,
                ),
                r,
            )
        except Exception:
            pass
        return False

    @asynccontextmanager
    async def locked_retrieval(
        self, memory_id: str, memory: Memory, db: AsyncSession
    ) -> AsyncIterator[None]:
        await self.take_snapshot(memory_id, memory)
        acquired = False
        deadline = asyncio.get_event_loop().time() + LOCK_ACQUIRE_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            acquired = await self.acquire_lock(memory_id)
            if acquired:
                break
            await asyncio.sleep(0.1)
        if not acquired:
            logger.warning(
                "Reconsolidation lock not acquired for %s after %ss; proceeding unlocked",
                memory_id,
                LOCK_ACQUIRE_TIMEOUT_SECONDS,
            )
        try:
            yield
        finally:
            res = await db.execute(select(Memory).where(Memory.id == memory.id))
            cur = res.scalar_one_or_none()
            if cur is not None:
                await self.verify_snapshot(memory_id, cur, db)
            if acquired:
                await self.release_lock(memory_id)


async def reconsolidation_status(memory_id: str, redis_client: Redis | None) -> dict[str, Any]:
    try:
        r = redis_client or await get_redis()
        lk = ns_key(f"{LOCK_PREFIX}{memory_id}")
        sk = ns_key(f"{SNAPSHOT_PREFIX}{memory_id}")
        lock_ttl = await r.ttl(lk)
        snap_ttl = await r.ttl(sk)
        is_locked = lock_ttl > 0
        has_snapshot = snap_ttl > 0
        lock_age = max(0, LOCK_TTL_SECONDS - int(lock_ttl)) if is_locked else None
        snap_age = max(0, SNAPSHOT_TTL_SECONDS - int(snap_ttl)) if has_snapshot else None
        return {
            "is_locked": is_locked,
            "has_snapshot": has_snapshot,
            "snapshot_age_seconds": snap_age,
            "lock_age_seconds": lock_age,
        }
    except Exception:
        return {
            "is_locked": False,
            "has_snapshot": False,
            "snapshot_age_seconds": None,
            "lock_age_seconds": None,
        }
