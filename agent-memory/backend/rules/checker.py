"""Evaluate rules: batch scan (:func:`collect_violations`) and post-write persist (:func:`check_memory_rules`)."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    Agent,
    Memory,
    MemoryProvenanceLog,
    RuleViolation as RuleViolationORM,
)
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import (
    get_redis,
    session_flagged_reads_cache_key,
    session_writes_cache_key,
)
from backend.rules.engine import (
    PREDEFINED_RULES,
    AgentStats,
    RuleContext,
    RuleViolation,
)


async def _agent_stats_for_memory(memory: Memory) -> AgentStats:
    redis = await get_redis()
    if memory.session_id is None:
        return AgentStats(
            session_write_count=0, flagged_reads_in_session=0, agent_registered=True
        )
    aid = str(memory.agent_id)
    sid = str(memory.session_id)
    wr = await redis.get(session_writes_cache_key(aid, sid))
    fr = await redis.get(session_flagged_reads_cache_key(aid, sid))
    return AgentStats(
        session_write_count=int(wr) if wr is not None else 0,
        flagged_reads_in_session=int(fr) if fr is not None else 0,
        agent_registered=True,
    )


def _redis_violation_cache_key(memory_id: str) -> str:
    return f"rule_violations:memory:{memory_id}"


async def _cache_violation(
    redis: Redis, memory_id: str, payload: dict[str, object]
) -> None:
    key = _redis_violation_cache_key(memory_id)
    await redis.lpush(key, json.dumps(payload, default=str))
    await redis.ltrim(key, 0, 99)


async def check_memory_rules(
    memory_id: str, db: AsyncSession, redis: Redis
) -> list[RuleViolation]:
    """Run all rules for one memory after write; persist rows, Redis cache, and MEDIUM+ notifications."""
    mid = uuid.UUID(memory_id)
    result = await db.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events))
        .where(Memory.id == mid)
    )
    memory = result.scalar_one_or_none()
    if memory is None or memory.is_deleted:
        return []

    agent_row = await db.execute(select(Agent).where(Agent.id == memory.agent_id))
    agent_registered = agent_row.scalar_one_or_none() is not None

    stats = await _agent_stats_for_memory(memory)
    stats = AgentStats(
        session_write_count=stats.session_write_count,
        flagged_reads_in_session=stats.flagged_reads_in_session,
        agent_registered=agent_registered,
    )

    if memory.session_id is not None:
        q_session = select(Memory).where(
            Memory.session_id == memory.session_id,
            Memory.is_deleted.is_(False),
        )
    else:
        q_session = select(Memory).where(
            Memory.agent_id == memory.agent_id,
            Memory.session_id.is_(None),
            Memory.is_deleted.is_(False),
        )
    sess_result = await db.execute(q_session)
    session_memories = list(sess_result.scalars().all())

    q_agent = select(Memory).where(
        Memory.agent_id == memory.agent_id, Memory.is_deleted.is_(False)
    )
    agent_result = await db.execute(q_agent)
    same_agent_memories = list(agent_result.scalars().all())

    prov = sorted(memory.provenance_events, key=lambda e: e.timestamp)
    if not prov:
        prov_result = await db.execute(
            select(MemoryProvenanceLog)
            .where(MemoryProvenanceLog.memory_id == memory.id)
            .order_by(MemoryProvenanceLog.timestamp.asc())
        )
        prov = list(prov_result.scalars().all())

    ctx = RuleContext(
        memory=memory,
        session_memories=session_memories,
        same_agent_memories=same_agent_memories,
        agent_stats=stats,
        provenance_events=prov,
    )

    violations: list[RuleViolation] = []
    for rule in PREDEFINED_RULES:
        hit = rule.check(ctx)
        if hit is not None:
            violations.append(hit)

    if not violations:
        return []

    persisted: list[RuleViolation] = []
    for v in violations:
        dup = await db.execute(
            select(RuleViolationORM).where(
                RuleViolationORM.memory_id == memory.id,
                RuleViolationORM.rule_name == v.rule_name,
                RuleViolationORM.is_acknowledged.is_(False),
            )
        )
        if dup.scalar_one_or_none() is not None:
            continue

        row = RuleViolationORM(
            id=uuid.uuid4(),
            memory_id=uuid.UUID(v.memory_id),
            agent_id=memory.agent_id,
            rule_name=v.rule_name,
            severity=v.severity,
            description=v.description,
            is_acknowledged=False,
            acknowledged_by=None,
            acknowledged_at=None,
            detected_at=v.detected_at,
            auto_flagged=v.auto_flagged,
            metadata_={
                "rule_description": next(
                    (r.description for r in PREDEFINED_RULES if r.name == v.rule_name),
                    "",
                ),
            },
        )
        db.add(row)
        await _cache_violation(
            redis,
            v.memory_id,
            {
                "id": str(row.id),
                "rule_name": v.rule_name,
                "severity": v.severity,
                "description": v.description,
                "detected_at": v.detected_at.isoformat(),
            },
        )
        persisted.append(v)

    await db.commit()

    for v in persisted:
        if v.severity in ("MEDIUM", "HIGH", "CRITICAL"):
            await push_notification(
                NotificationEvent(
                    id=str(uuid.uuid4()),
                    type="rule_violation",
                    severity=v.severity,
                    title=f"Rule violation: {v.rule_name}",
                    message=v.description,
                    memory_id=v.memory_id,
                    agent_id=v.agent_id,
                    rule_name=v.rule_name,
                    timestamp=datetime.now(timezone.utc),
                    read=False,
                ),
                redis,
            )

    return violations


async def collect_violations(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID | None = None,
) -> list[RuleViolation]:
    """Run all predefined rules on non-deleted memories (batch scan; does not persist)."""
    result = await db.execute(
        select(Memory)
        .where(Memory.is_deleted.is_(False))
        .options(selectinload(Memory.provenance_events))
    )
    memories: list[Memory] = list(result.scalars().unique().all())

    if agent_id is not None:
        memories = [m for m in memories if m.agent_id == agent_id]

    by_session: dict[uuid.UUID | None, list[Memory]] = defaultdict(list)
    by_agent: dict[uuid.UUID, list[Memory]] = defaultdict(list)
    for m in memories:
        by_session[m.session_id].append(m)
        by_agent[m.agent_id].append(m)

    prov_result = await db.execute(select(MemoryProvenanceLog))
    prov_rows = list(prov_result.scalars().all())
    prov_by_memory: dict[uuid.UUID, list[MemoryProvenanceLog]] = defaultdict(list)
    for e in prov_rows:
        prov_by_memory[e.memory_id].append(e)

    violations: list[RuleViolation] = []
    agent_ids = {m.agent_id for m in memories}
    if agent_ids:
        reg = await db.execute(select(Agent.id).where(Agent.id.in_(agent_ids)))
        registered = {r for r in reg.scalars().all()}
    else:
        registered = set()

    for mem in memories:
        session_mem = [x for x in by_session[mem.session_id] if not x.is_deleted]
        same_agent = [x for x in by_agent[mem.agent_id] if not x.is_deleted]
        base_stats = await _agent_stats_for_memory(mem)
        stats = AgentStats(
            session_write_count=base_stats.session_write_count,
            flagged_reads_in_session=base_stats.flagged_reads_in_session,
            agent_registered=mem.agent_id in registered,
        )
        events = sorted(prov_by_memory.get(mem.id, []), key=lambda e: e.timestamp)
        ctx = RuleContext(
            memory=mem,
            session_memories=session_mem,
            same_agent_memories=same_agent,
            agent_stats=stats,
            provenance_events=events,
        )
        for rule in PREDEFINED_RULES:
            v = rule.check(ctx)
            if v is not None:
                violations.append(v)

    return violations
