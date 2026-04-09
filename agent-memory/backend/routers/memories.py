"""Memory CRUD, listing, provenance, and soft delete."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import get_db, log_memory_event
from backend.models import Agent, Memory, MemoryProvenanceLog
from backend.redis_client import (
    get_redis,
    session_flagged_reads_cache_key,
    session_writes_cache_key,
    trust_cache_key,
)
from backend.schemas import (
    MemoryCreate,
    MemoryCreateResponse,
    MemoryDetail,
    MemoryFlagBody,
    MemoryListItem,
    MemoryListResponse,
    MemoryProvenanceEvent,
)

router = APIRouter(prefix="/memories", tags=["memories"])
settings = get_settings()


@router.post("", response_model=MemoryCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: MemoryCreate,
    db: AsyncSession = Depends(get_db),
) -> MemoryCreateResponse:
    agent_result = await db.execute(select(Agent).where(Agent.id == body.agent_id))
    if agent_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    memory = Memory(
        content=body.content,
        agent_id=body.agent_id,
        source_type=body.source_type,
        source_identifier=body.source_identifier,
        safety_context=body.safety_context,
        session_id=body.session_id,
    )
    db.add(memory)
    await db.flush()

    await log_memory_event(
        db,
        memory_id=memory.id,
        event_type="write",
        performed_by_agent_id=body.agent_id,
        event_metadata={
            "source_type": body.source_type,
            "source_identifier": body.source_identifier,
            "session_id": str(body.session_id) if body.session_id else None,
        },
    )

    redis = await get_redis()
    await redis.set(
        trust_cache_key(str(memory.id)),
        str(memory.trust_score),
        ex=settings.trust_cache_ttl_seconds,
    )

    if body.session_id is not None:
        key = session_writes_cache_key(str(body.agent_id), str(body.session_id))
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.session_writes_cache_ttl_seconds)

    await db.commit()
    await db.refresh(memory)
    return MemoryCreateResponse(
        memory_id=memory.id, trust_score=memory.trust_score, created_at=memory.created_at
    )


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    agent_id: uuid.UUID | None = Query(default=None),
    source_type: str | None = Query(default=None),
    min_trust_score: float | None = Query(default=None, ge=0.0, le=1.0),
    flagged_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> MemoryListResponse:
    conditions: list[Any] = [Memory.is_deleted.is_(False)]
    if agent_id is not None:
        conditions.append(Memory.agent_id == agent_id)
    if source_type is not None:
        conditions.append(Memory.source_type == source_type)
    if min_trust_score is not None:
        conditions.append(Memory.trust_score >= min_trust_score)
    if flagged_only:
        conditions.append(Memory.is_flagged.is_(True))

    count_q = select(func.count()).select_from(Memory).where(*conditions)
    total_result = await db.execute(count_q)
    total = int(total_result.scalar_one())

    list_result = await db.execute(
        select(Memory, Agent.name)
        .join(Agent, Agent.id == Memory.agent_id)
        .where(*conditions)
        .order_by(Memory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list_result.all()
    items: list[MemoryListItem] = []
    for m, agent_name in rows:
        item = MemoryListItem.model_validate(m)
        item.agent_name = agent_name
        items.append(item)
    return MemoryListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{memory_id}/provenance", response_model=list[MemoryProvenanceEvent])
async def get_memory_provenance(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[MemoryProvenanceEvent]:
    mem_result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = mem_result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    prov_result = await db.execute(
        select(MemoryProvenanceLog)
        .where(MemoryProvenanceLog.memory_id == memory_id)
        .order_by(MemoryProvenanceLog.timestamp.asc())
    )
    events = prov_result.scalars().all()
    return [MemoryProvenanceEvent.model_validate(e) for e in events]


@router.post("/{memory_id}/flag", status_code=status.HTTP_200_OK)
async def flag_memory(
    memory_id: uuid.UUID,
    body: MemoryFlagBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is None or memory.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    memory.is_flagged = True
    memory.flag_reason = body.reason

    await log_memory_event(
        db,
        memory_id=memory.id,
        event_type="anomaly_flagged",
        performed_by_agent_id=body.performed_by_agent_id,
        event_metadata={"reason": body.reason},
    )

    redis = await get_redis()
    await redis.set(
        trust_cache_key(str(memory.id)),
        str(memory.trust_score),
        ex=settings.trust_cache_ttl_seconds,
    )

    await db.commit()
    await db.refresh(memory)
    return {
        "memory_id": memory.id,
        "flagged": memory.is_flagged,
        "reason": memory.flag_reason,
    }


@router.get("/{memory_id}", response_model=MemoryDetail)
async def get_memory(
    memory_id: uuid.UUID,
    reader_agent_id: uuid.UUID | None = Query(
        default=None,
        description="Optional agent id to attribute this read in the provenance log",
    ),
    reader_session_id: uuid.UUID | None = Query(
        default=None,
        description="Optional reader session id for trust-chain contamination tracking",
    ),
    db: AsyncSession = Depends(get_db),
) -> MemoryDetail:
    result = await db.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events), selectinload(Memory.agent))
        .where(Memory.id == memory_id)
    )
    memory = result.unique().scalar_one_or_none()
    if memory is None or memory.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    await log_memory_event(
        db,
        memory_id=memory.id,
        event_type="read",
        performed_by_agent_id=reader_agent_id,
        event_metadata={
            "reader_session_id": str(reader_session_id) if reader_session_id else None,
        },
    )

    redis = await get_redis()
    if (
        reader_agent_id is not None
        and reader_session_id is not None
        and memory.is_flagged
    ):
        fk = session_flagged_reads_cache_key(str(reader_agent_id), str(reader_session_id))
        c = await redis.incr(fk)
        if c == 1:
            await redis.expire(fk, settings.session_writes_cache_ttl_seconds)

    await redis.set(
        trust_cache_key(str(memory.id)),
        str(memory.trust_score),
        ex=settings.trust_cache_ttl_seconds,
    )

    await db.commit()

    reload = await db.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events), selectinload(Memory.agent))
        .where(Memory.id == memory_id)
    )
    memory = reload.unique().scalar_one()
    provenance = sorted(memory.provenance_events, key=lambda e: e.timestamp)
    agent_name = memory.agent.name if memory.agent is not None else None
    return MemoryDetail(
        id=memory.id,
        content=memory.content,
        agent_id=memory.agent_id,
        agent_name=agent_name,
        source_type=memory.source_type,
        source_identifier=memory.source_identifier,
        safety_context=memory.safety_context,
        trust_score=memory.trust_score,
        is_flagged=memory.is_flagged,
        flag_reason=memory.flag_reason,
        session_id=memory.session_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        is_deleted=memory.is_deleted,
        provenance=[MemoryProvenanceEvent.model_validate(e) for e in provenance],
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    performed_by_agent_id: uuid.UUID | None = Query(
        default=None,
        description="Optional agent id to attribute this deletion in the provenance log",
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    if memory.is_deleted:
        return None

    memory.is_deleted = True
    await log_memory_event(
        db,
        memory_id=memory.id,
        event_type="deleted",
        performed_by_agent_id=performed_by_agent_id,
        event_metadata={"soft_delete": True},
    )

    redis = await get_redis()
    await redis.delete(trust_cache_key(str(memory.id)))

    await db.commit()
