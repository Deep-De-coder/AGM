"""Memory CRUD, listing, provenance, and soft delete."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import backend.database as database
from backend.config import get_settings
from backend.database import get_db, log_memory_event
from backend.dendritic_cell import DendriticCellAgent
from backend.lib.baseline import update_behavioral_baseline
from backend.lib.behavioral_hash import update_agent_behavioral_hash
from backend.lib.content_address import compute_content_hash, verify_memory_integrity
from backend.lib.quorum_trust import compute_quorum_score, quorum_to_dict
from backend.lib.reconsolidation import ReconsolidationGuard, reconsolidation_status
from backend.lib.vector_clock import (
    compute_causal_depth,
    compute_causal_parents,
    increment_clock,
    validate_causal_chain,
)
from backend.models import (
    Agent,
    Memory,
    MemoryProvenanceLog,
)
from backend.models import (
    RuleViolation as RuleViolationORM,
)
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import (
    get_redis,
    ns_key,
    session_flagged_reads_cache_key,
    session_writes_cache_key,
    trust_cache_key,
)
from backend.rules.checker import check_memory_rules
from backend.schemas import (
    MemoryCreate,
    MemoryCreateResponse,
    MemoryDetail,
    MemoryFlagBody,
    MemoryListItem,
    MemoryListResponse,
    MemoryProvenanceEvent,
)
from backend.trust_engine import compute_trust_score, determine_initial_memory_state

router = APIRouter(prefix="/memories", tags=["memories"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _reality_score_from_safety(safety: dict[str, Any]) -> float | None:
    raw = (safety or {}).get("reality_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def _run_rule_checks_after_write(memory_id: str) -> None:
    from backend.redis_client import get_redis
    from backend.rules.checker import check_memory_rules

    try:
        async with database.AsyncSessionLocal() as session:
            redis = await get_redis()
            await check_memory_rules(memory_id, session, redis)
    except Exception:
        logger.exception("Background rule check failed for memory_id=%s", memory_id)


@router.post(
    "", response_model=MemoryCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_memory(
    background_tasks: BackgroundTasks,
    body: MemoryCreate,
    db: AsyncSession = Depends(get_db),
) -> MemoryCreateResponse:
    agent_result = await db.execute(select(Agent).where(Agent.id == body.agent_id))
    if agent_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )

    mem_payload = body.model_dump()
    memory = Memory(
        content=body.content,
        agent_id=body.agent_id,
        source_type=body.source_type,
        source_identifier=body.source_identifier,
        safety_context=body.safety_context,
        session_id=body.session_id,
        memory_state=determine_initial_memory_state(mem_payload),
        reality_score=_reality_score_from_safety(body.safety_context),
    )
    db.add(memory)
    await db.flush()

    memory.content_hash = compute_content_hash(
        {
            "content": memory.content,
            "agent_id": memory.agent_id,
            "session_id": memory.session_id,
            "source_type": memory.source_type,
            "source_identifier": memory.source_identifier,
            "created_at": memory.created_at,
        }
    )
    memory.content_hash_valid = True

    redis = await get_redis()
    parents = await compute_causal_parents(body.agent_id, body.session_id, db)
    clock = await increment_clock(str(body.agent_id), redis)
    depth = await compute_causal_depth(parents, db)
    memory.causal_parents = parents
    memory.vector_clock = clock
    memory.causal_depth = depth

    valid, reason = await validate_causal_chain(memory, db)
    if not valid:
        await log_memory_event(
            db,
            memory_id=memory.id,
            event_type="anomaly_flagged",
            performed_by_agent_id=body.agent_id,
            event_metadata={"causal_validation": reason},
        )

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
    await update_behavioral_baseline(db, body.agent_id, memory)
    b_hash, drift = await update_agent_behavioral_hash(body.agent_id, memory, db)

    quorum = await compute_quorum_score(
        str(body.agent_id), body.session_id, db, redis
    )
    try:
        await redis.lpush(
            ns_key(f"fast:writes:{body.agent_id}"),
            str(datetime.now(timezone.utc).timestamp()),
        )
        await redis.ltrim(ns_key(f"fast:writes:{body.agent_id}"), 0, 9)
        await redis.expire(ns_key(f"fast:writes:{body.agent_id}"), 3600)
    except Exception:
        pass

    quorum_warning: str | None = None
    if quorum.quorum_status == "FAILED_QUORUM":
        memory.memory_state = "anergic"
        quorum_warning = (
            f"Agent failed quorum ({quorum.failing_signals}) — "
            "memory quarantined to anergic state"
        )
        try:
            ag = (
                await db.execute(select(Agent).where(Agent.id == body.agent_id))
            ).scalar_one()
            await push_notification(
                NotificationEvent(
                    id=str(uuid.uuid4()),
                    type="rule_violation",
                    severity="HIGH",
                    title="Quorum failure",
                    message=(
                        f"QUORUM FAILURE: Agent {ag.name} failing "
                        f"{quorum.failing_signals}. New memory {memory.id} set to anergic."
                    ),
                    memory_id=str(memory.id),
                    agent_id=str(body.agent_id),
                    rule_name="QUORUM",
                    timestamp=datetime.now(timezone.utc),
                    read=False,
                ),
                redis,
            )
        except Exception:
            pass

    dca = DendriticCellAgent(database.AsyncSessionLocal, redis)
    dca_ctx = await dca.get_agent_context(str(body.agent_id))
    dca_warning: str | None = None
    if dca_ctx.net_context == "SEMI_MATURE":
        memory.memory_state = "anergic"
    if dca_ctx.net_context == "MATURE_DANGER":
        memory.is_flagged = True
        memory.flag_reason = "DCA: Agent in MATURE_DANGER context at write time"
        dca_warning = (
            "Agent context is MATURE_DANGER — memory stored but flagged for review"
        )

    await db.commit()
    await db.refresh(memory)
    background_tasks.add_task(_run_rule_checks_after_write, str(memory.id))
    return MemoryCreateResponse(
        memory_id=memory.id,
        trust_score=memory.trust_score,
        created_at=memory.created_at,
        dca_warning=dca_warning,
        behavioral_hash=b_hash,
        behavioral_drift=drift,
        content_hash=memory.content_hash[:16] if memory.content_hash else None,
        quorum=quorum_to_dict(quorum),
        quorum_warning=quorum_warning,
        rules_check="pending",
    )


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    agent_id: uuid.UUID | None = Query(default=None),
    source_type: str | None = Query(default=None),
    memory_state: str | None = Query(default=None),
    min_trust_score: float | None = Query(default=None, ge=0.0, le=1.0),
    flagged_only: bool = Query(default=False),
    requesting_agent_id: uuid.UUID | None = Query(
        default=None,
        description="Caller agent id (alternative to X-Agent-Id header).",
    ),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    verify_integrity: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> MemoryListResponse | JSONResponse:
    if memory_state == "anergic":
        caller = requesting_agent_id
        if caller is None and x_agent_id:
            try:
                caller = uuid.UUID(x_agent_id.strip())
            except ValueError:
                caller = None
        if caller is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent id required (X-Agent-Id header or requesting_agent_id).",
            )
        dup = await db.execute(
            select(RuleViolationORM).where(
                RuleViolationORM.memory_id.is_(None),
                RuleViolationORM.rule_name == "RULE_013",
                RuleViolationORM.agent_id == caller,
                RuleViolationORM.is_acknowledged.is_(False),
            )
        )
        if dup.scalar_one_or_none() is None:
            row = RuleViolationORM(
                id=uuid.uuid4(),
                memory_id=None,
                agent_id=caller,
                rule_name="RULE_013",
                severity="CRITICAL",
                description=(
                    "Agent queried specifically for anergic memories — "
                    "legitimate agents use get_safe_memories"
                ),
                is_acknowledged=False,
                acknowledged_by=None,
                acknowledged_at=None,
                detected_at=datetime.now(timezone.utc),
                auto_flagged=True,
                metadata_={"rule_description": "Direct anergic listing attempt"},
            )
            db.add(row)
            await db.commit()
        redis = await get_redis()
        await push_notification(
            NotificationEvent(
                id=str(uuid.uuid4()),
                type="rule_violation",
                severity="CRITICAL",
                title="Rule violation: RULE_013",
                message=(
                    "Agent queried specifically for anergic memories — "
                    "legitimate agents use get_safe_memories"
                ),
                memory_id="",
                agent_id=str(caller),
                rule_name="RULE_013",
                timestamp=datetime.now(timezone.utc),
                read=False,
            ),
            redis,
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": (
                    "Direct anergic memory queries are not permitted. "
                    "Use GET /memories/safe for filtered results."
                )
            },
        )

    conditions: list[Any] = [Memory.is_deleted.is_(False)]
    if agent_id is not None:
        conditions.append(Memory.agent_id == agent_id)
    if source_type is not None:
        conditions.append(Memory.source_type == source_type)
    if memory_state is not None:
        conditions.append(Memory.memory_state == memory_state)
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
    redis = await get_redis()
    guard = ReconsolidationGuard(redis)

    async def _snap(mem: Memory) -> None:
        try:
            await guard.take_snapshot(str(mem.id), mem)
        except Exception:
            logger.debug("list snapshot failed for %s", mem.id, exc_info=True)

    for m, agent_name in rows:
        item = MemoryListItem.model_validate(m)
        item.agent_name = agent_name
        items.append(item)
        asyncio.create_task(_snap(m))

    if verify_integrity:
        extra: list[dict[str, Any]] = []
        for m, _ in rows:
            v = await verify_memory_integrity(m, db, redis)
            extra.append({"memory_id": str(m.id), "integrity": v})
        await db.commit()
        return JSONResponse(
            content={
                "items": [i.model_dump() for i in items],
                "total": total,
                "limit": limit,
                "offset": offset,
                "integrity_details": extra,
            }
        )

    return MemoryListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/safe", response_model=list[MemoryListItem])
async def list_safe_memories(
    agent_id: uuid.UUID | None = Query(default=None),
    min_trust_score: float = Query(default=0.6, ge=0.0, le=1.0),
    limit: int = Query(default=10, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[MemoryListItem]:
    """Safe path: high-trust, non-anergic, non-quarantined, not flagged, no open violations."""
    unresolved = exists().where(
        RuleViolationORM.memory_id == Memory.id,
        RuleViolationORM.is_acknowledged.is_(False),
    )
    conditions: list[Any] = [
        Memory.is_deleted.is_(False),
        Memory.trust_score >= min_trust_score,
        Memory.memory_state.not_in(("anergic", "quarantined")),
        Memory.is_flagged.is_(False),
        ~unresolved,
    ]
    if agent_id is not None:
        conditions.append(Memory.agent_id == agent_id)

    list_result = await db.execute(
        select(Memory, Agent.name)
        .join(Agent, Agent.id == Memory.agent_id)
        .where(*conditions)
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    rows = list_result.all()
    out: list[MemoryListItem] = []
    for m, agent_name in rows:
        item = MemoryListItem.model_validate(m)
        item.agent_name = agent_name
        out.append(item)
    return out


@router.post("/{memory_id}/check-rules", status_code=status.HTTP_200_OK)
async def run_memory_rules_check(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, float | int | bool | list[dict[str, object]]]:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is None or memory.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )

    redis = await get_redis()
    violations = await check_memory_rules(str(memory_id), db, redis)
    out_list: list[dict[str, object]] = []
    for v in violations:
        out_list.append(
            {
                "rule_name": v.rule_name,
                "severity": v.severity,
                "description": v.description,
                "detected_at": v.detected_at.isoformat(),
            }
        )
    return {
        "violations_found": len(violations),
        "violations": out_list,
        "all_clear": len(violations) == 0,
    }


@router.get("/{memory_id}/provenance", response_model=list[MemoryProvenanceEvent])
async def get_memory_provenance(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[MemoryProvenanceEvent]:
    mem_result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = mem_result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )

    redis = await get_redis()
    guard = ReconsolidationGuard(redis)
    ok = await guard.verify_snapshot(str(memory_id), memory, db)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Memory state changed during retrieval window. "
                "Reload memory before flagging."
            ),
        )

    memory.is_flagged = True
    memory.flag_reason = body.reason

    await log_memory_event(
        db,
        memory_id=memory.id,
        event_type="anomaly_flagged",
        performed_by_agent_id=body.performed_by_agent_id,
        event_metadata={"reason": body.reason},
    )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )

    redis = await get_redis()
    guard = ReconsolidationGuard(redis)
    async with guard.locked_retrieval(str(memory_id), memory, db):
        await log_memory_event(
            db,
            memory_id=memory.id,
            event_type="read",
            performed_by_agent_id=reader_agent_id,
            event_metadata={
                "reader_session_id": str(reader_session_id) if reader_session_id else None,
            },
        )

        if (
            reader_agent_id is not None
            and reader_session_id is not None
            and memory.is_flagged
        ):
            fk = session_flagged_reads_cache_key(
                str(reader_agent_id), str(reader_session_id)
            )
            c = await redis.incr(fk)
            if c == 1:
                await redis.expire(fk, settings.session_writes_cache_ttl_seconds)

        await redis.set(
            trust_cache_key(str(memory.id)),
            str(memory.trust_score),
            ex=settings.trust_cache_ttl_seconds,
        )

        await db.commit()

    db.expire_all()

    reload = await db.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events), selectinload(Memory.agent))
        .where(Memory.id == memory_id)
    )
    memory = reload.unique().scalar_one()

    chain_ok, chain_reason = await validate_causal_chain(memory, db)
    integ = await verify_memory_integrity(memory, db, redis)
    await db.commit()
    await db.refresh(memory)

    now = datetime.now(timezone.utc)
    created = memory.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_sec = (now - created).total_seconds()
    if not chain_ok and age_sec > 5.0:
        memory.is_flagged = True
        memory.flag_reason = f"CAUSAL VIOLATION: {chain_reason}"
        await db.commit()
        await push_notification(
            NotificationEvent(
                id=str(uuid.uuid4()),
                type="rule_violation",
                severity="HIGH",
                title="Causal chain violation",
                message=str(chain_reason),
                memory_id=str(memory.id),
                agent_id=str(memory.agent_id),
                rule_name="CAUSAL",
                timestamp=datetime.now(timezone.utc),
                read=False,
            ),
            redis,
        )
        await db.refresh(memory)

    fresh_trust = await compute_trust_score(memory, db, redis)
    trust_recomputed = True
    if abs(float(fresh_trust) - float(memory.trust_score)) > 0.05:
        old_trust = float(memory.trust_score)
        memory.trust_score = float(fresh_trust)
        await log_memory_event(
            db,
            memory_id=memory.id,
            event_type="trust_update",
            performed_by_agent_id=None,
            event_metadata={
                "old_trust": old_trust,
                "new_trust": float(fresh_trust),
                "reason": "stale_recompute_on_read",
            },
        )
        await db.commit()
        await db.refresh(memory)

    live_q = await compute_quorum_score(
        str(memory.agent_id),
        str(memory.session_id) if memory.session_id else None,
        db,
        redis,
    )
    live_quorum = {
        "status": live_q.quorum_status,
        "composite_score": live_q.composite_score,
        "memory_trust_multiplier": live_q.memory_trust_multiplier,
        "failing_signals": live_q.failing_signals,
    }
    quorum_warning: str | None = None
    if live_q.quorum_status == "FAILED_QUORUM" and memory.memory_state == "active":
        quorum_warning = (
            "Agent currently in FAILED_QUORUM — "
            "memory state may be downgraded on next trust pass"
        )

    rec = await reconsolidation_status(str(memory_id), redis)
    integrity_block: dict[str, Any] = dict(integ)
    if not integ.get("valid", True):
        integrity_block["violation_detected_at"] = datetime.now(timezone.utc).isoformat()

    causal = {
        "parents": memory.causal_parents or [],
        "vector_clock": memory.vector_clock or {},
        "causal_depth": memory.causal_depth,
        "chain_valid": chain_ok,
        "chain_violation": None if chain_ok else chain_reason,
    }

    provenance = sorted(memory.provenance_events, key=lambda e: e.timestamp)
    agent_name = memory.agent.name if memory.agent is not None else None
    await guard.take_snapshot(str(memory_id), memory)
    return MemoryDetail(
        id=memory.id,
        content=memory.content,
        agent_id=memory.agent_id,
        agent_name=agent_name,
        source_type=memory.source_type,
        source_identifier=memory.source_identifier,
        safety_context=memory.safety_context,
        trust_score=float(fresh_trust),
        is_flagged=memory.is_flagged,
        flag_reason=memory.flag_reason,
        session_id=memory.session_id,
        memory_state=memory.memory_state,
        reality_score=memory.reality_score,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        is_deleted=memory.is_deleted,
        provenance=[MemoryProvenanceEvent.model_validate(e) for e in provenance],
        reconsolidation=rec,
        integrity=integrity_block,
        causal=causal,
        content_hash=memory.content_hash[:16] if memory.content_hash else None,
        content_hash_valid=memory.content_hash_valid,
        trust_recomputed=trust_recomputed,
        live_quorum=live_quorum,
        quorum_warning=quorum_warning,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )
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
