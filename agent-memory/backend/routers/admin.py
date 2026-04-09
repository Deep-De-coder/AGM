"""Administrative operations."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.lib.content_address import verify_memory_integrity
from backend.models import (
    Agent,
    Memory,
    MemoryProvenanceLog,
    RuleViolation,
    TrustMetricSnapshot,
)
from backend.models import (
    Session as SessionRow,
)
from backend.notifications import NOTIFICATIONS_LIST_KEY, NOTIFICATIONS_READ_SET_KEY
from backend.redis_client import get_redis
from backend.trust_engine import (
    consolidate_memories,
    promote_anergic_memories,
    quarantine_contradicting_memories,
    run_trust_pass,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/run-trust-decay", status_code=status.HTTP_200_OK)
async def run_trust_decay(db: AsyncSession = Depends(get_db)) -> dict[str, int | float]:
    return await run_trust_pass(db, manual=True)


class SessionSeedBody(BaseModel):
    """Create a session row for context_hash linkage (tests / demos)."""

    id: uuid.UUID | None = None
    context_hash: str = Field(..., min_length=1, max_length=256)
    agent_id: uuid.UUID | None = None
    outcome: str | None = Field(default=None, max_length=32)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def seed_session(
    body: SessionSeedBody, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    sid = body.id or uuid.uuid4()
    row = SessionRow(
        id=sid,
        context_hash=body.context_hash,
        agent_id=body.agent_id,
        outcome=body.outcome,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "context_hash": row.context_hash or ""}


@router.post("/consolidate", status_code=status.HTTP_200_OK)
async def admin_consolidate(db: AsyncSession = Depends(get_db)) -> dict[str, str | int]:
    consolidated = await consolidate_memories(db)
    promoted = await promote_anergic_memories(db)
    quarantined = await quarantine_contradicting_memories(db)
    await db.commit()
    return {
        "consolidated": consolidated,
        "promoted_from_anergic": promoted,
        "quarantined": quarantined,
        "triggered_at": datetime.utcnow().isoformat(),
    }


@router.post("/reset-demo-data", status_code=status.HTTP_200_OK)
async def reset_demo_data(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Delete all agents, memories, and related rows; clear session/trust Redis keys."""
    await db.execute(delete(MemoryProvenanceLog))
    await db.execute(delete(RuleViolation))
    await db.execute(delete(TrustMetricSnapshot))
    await db.execute(delete(Memory))
    await db.execute(delete(SessionRow))
    await db.execute(delete(Agent))
    await db.commit()

    redis = await get_redis()
    for pattern in (
        "writes:*",
        "flagged_reads:*",
        "trust:*",
        "rule_violations:memory:*",
    ):
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
    await redis.delete(NOTIFICATIONS_LIST_KEY)
    await redis.delete(NOTIFICATIONS_READ_SET_KEY)

    return {"status": "ok", "message": "All demo data cleared."}


@router.post("/verify-integrity", status_code=status.HTTP_200_OK)
async def verify_integrity(
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    redis = await get_redis()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    res = await db.execute(
        select(Memory).where(
            Memory.content_hash.isnot(None),
            or_(
                Memory.content_hash_verified_at.is_(None),
                Memory.content_hash_verified_at < cutoff,
            ),
        )
    )
    rows = list(res.scalars().all())
    total_checked = 0
    valid = 0
    tampered = 0
    tampered_memory_ids: list[str] = []
    for i in range(0, len(rows), 100):
        batch = rows[i : i + 100]
        for m in batch:
            total_checked += 1
            r = await verify_memory_integrity(m, db, redis)
            if r.get("valid"):
                valid += 1
            else:
                tampered += 1
                tampered_memory_ids.append(str(m.id))
    await db.commit()
    return {
        "total_checked": total_checked,
        "valid": valid,
        "tampered": tampered,
        "tampered_memory_ids": tampered_memory_ids,
        "scan_completed_at": datetime.now(timezone.utc).isoformat(),
    }
