"""Vector clocks and causal parent selection for memories."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Memory, MemoryProvenanceLog
from backend.redis_client import get_redis, ns_key

_VCLOCK_TTL = 86400  # 24 hours


async def get_current_vector_clock(agent_id: str, redis_client: Redis | None) -> dict[str, int]:
    try:
        r = redis_client or await get_redis()
        raw = await r.get(ns_key(f"vclock:{agent_id}"))
        if not raw:
            return {str(agent_id): 0}
        import json

        data = json.loads(raw)
        return {str(k): int(v) for k, v in data.items()}
    except Exception:
        return {str(agent_id): 0}


async def increment_clock(
    agent_id: str,
    redis_client: Redis | None,
    merge_with: dict[str, int] | None = None,
) -> dict[str, int]:
    try:
        r = redis_client or await get_redis()
        cur = await get_current_vector_clock(agent_id, r)
        aid = str(agent_id)
        cur[aid] = int(cur.get(aid, 0)) + 1
        if merge_with:
            for k, v in merge_with.items():
                sk = str(k)
                cur[sk] = max(int(cur.get(sk, 0)), int(v))
        import json

        payload = json.dumps(cur, sort_keys=True)
        await r.set(ns_key(f"vclock:{aid}"), payload, ex=_VCLOCK_TTL)
        return cur
    except Exception:
        aid = str(agent_id)
        return {aid: 1}


async def compute_causal_parents(
    agent_id: uuid.UUID,
    session_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[str]:
    if session_id is None:
        return []
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    q = (
        select(MemoryProvenanceLog.memory_id)
        .join(Memory, Memory.id == MemoryProvenanceLog.memory_id)
        .where(
            MemoryProvenanceLog.event_type == "read",
            MemoryProvenanceLog.performed_by_agent_id == agent_id,
            Memory.session_id == session_id,
            Memory.is_deleted.is_(False),
            MemoryProvenanceLog.timestamp >= since,
        )
        .order_by(MemoryProvenanceLog.timestamp.desc())
        .limit(5)
    )
    res = await db.execute(q)
    mids = [str(r[0]) for r in res.all()]
    seen: set[str] = set()
    out: list[str] = []
    for mid in mids:
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    if not out:
        prev = await db.execute(
            select(Memory.id)
            .where(
                Memory.session_id == session_id,
                Memory.agent_id == agent_id,
                Memory.is_deleted.is_(False),
            )
            .order_by(Memory.created_at.desc())
            .limit(1)
        )
        p = prev.scalar_one_or_none()
        if p is not None:
            out.append(str(p))
    return out


async def validate_causal_chain(
    memory: Memory,
    db: AsyncSession,
) -> tuple[bool, str]:
    parents = list(memory.causal_parents or [])
    sid = memory.session_id
    aid = memory.agent_id

    first_q = await db.execute(
        select(Memory.id)
        .where(
            Memory.session_id == sid,
            Memory.agent_id == aid,
            Memory.is_deleted.is_(False),
        )
        .order_by(Memory.created_at.asc())
        .limit(1)
    )
    first_id = first_q.scalar_one_or_none()
    is_first = first_id is not None and first_id == memory.id

    if not parents and sid is not None and not is_first:
        return (
            False,
            "CAUSAL_ORPHAN: Memory has no causal parents but is not the first memory in session",
        )

    vc_self = dict(memory.vector_clock or {})

    for pid in parents:
        try:
            puid = uuid.UUID(pid)
        except ValueError:
            return False, f"INVALID_PARENT: Parent {pid} is not a valid UUID"
        pr = await db.execute(select(Memory).where(Memory.id == puid))
        parent = pr.scalar_one_or_none()
        if parent is None:
            return False, f"INVALID_PARENT: Parent {pid} does not exist"
        if parent.created_at > memory.created_at:
            return (
                False,
                f"TEMPORAL_PARADOX: Parent {pid} was created AFTER this memory — impossible provenance",
            )
        pvc = parent.vector_clock or {}
        for ag, pv in pvc.items():
            sag = str(ag)
            if int(vc_self.get(sag, 0)) < int(pv):
                return (
                    False,
                    f"CLOCK_REGRESSION: Memory claims to follow {pid} but its vector clock is behind parent's clock",
                )

    return True, "valid"


async def compute_causal_depth(
    causal_parents: list[str],
    db: AsyncSession,
) -> int:
    if not causal_parents:
        return 0
    uids = []
    for p in causal_parents:
        try:
            uids.append(uuid.UUID(p))
        except ValueError:
            continue
    if not uids:
        return 0
    res = await db.execute(select(Memory).where(Memory.id.in_(uids)))
    parents = list(res.scalars().all())
    if not parents:
        return 0
    return max(int(p.causal_depth or 0) for p in parents) + 1
