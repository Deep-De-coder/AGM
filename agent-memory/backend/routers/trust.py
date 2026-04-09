"""Trust score updates with provenance and Redis cache."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db, log_memory_event
from backend.models import Memory, TrustMetricSnapshot
from backend.redis_client import get_redis, trust_cache_key
from backend.schemas import TrustUpdate

router = APIRouter(prefix="/memories", tags=["trust"])
alias_router = APIRouter(prefix="/trust", tags=["trust"])
settings = get_settings()


async def fetch_memory_trust_payload(
    memory_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, float | uuid.UUID | bool | str | None]:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is None or memory.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )
    snap_row = await db.execute(
        select(
            func.count(TrustMetricSnapshot.id),
            func.max(TrustMetricSnapshot.created_at),
        ).where(TrustMetricSnapshot.memory_id == memory_id)
    )
    cnt, last_at = snap_row.one()
    return {
        "memory_id": memory.id,
        "trust_score": memory.trust_score,
        "is_flagged": memory.is_flagged,
        "flag_reason": memory.flag_reason,
        "last_computed_at": last_at.isoformat() if last_at is not None else None,
        "snapshot_count": int(cnt or 0),
    }


@router.get("/{memory_id}/trust", status_code=status.HTTP_200_OK)
async def get_memory_trust(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, float | uuid.UUID | bool | str | None]:
    return await fetch_memory_trust_payload(memory_id, db)


@alias_router.get("/{memory_id}", status_code=status.HTTP_200_OK)
async def get_trust_alias(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, float | uuid.UUID | bool | str | None]:
    return await fetch_memory_trust_payload(memory_id, db)


@router.patch("/{memory_id}/trust", status_code=status.HTTP_200_OK)
async def update_memory_trust(
    memory_id: uuid.UUID,
    body: TrustUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, float | uuid.UUID]:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is None or memory.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )

    previous = memory.trust_score
    memory.trust_score = body.trust_score

    await log_memory_event(
        db,
        memory_id=memory.id,
        event_type="trust_update",
        performed_by_agent_id=body.performed_by_agent_id,
        event_metadata={
            "previous_trust_score": previous,
            "new_trust_score": body.trust_score,
            "reason": body.reason,
        },
    )

    redis = await get_redis()
    await redis.set(
        trust_cache_key(str(memory.id)),
        str(memory.trust_score),
        ex=settings.trust_cache_ttl_seconds,
    )

    await db.commit()
    await db.refresh(memory)
    return {"memory_id": memory.id, "trust_score": memory.trust_score}
