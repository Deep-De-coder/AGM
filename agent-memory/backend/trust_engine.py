"""Trust decay and anomaly detection (background + manual run)."""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import Memory, TrustMetricSnapshot
from backend.database import log_memory_event
from backend.redis_client import (
    get_redis,
    session_flagged_reads_cache_key,
    session_writes_cache_key,
    trust_cache_key,
)

settings = get_settings()

DECAY_RATE_BY_SOURCE: dict[str, float] = {
    "user_input": 0.005,
    "tool_call": 0.003,
    "inter_agent": 0.02,
    "web_fetch": 0.015,
}
DEFAULT_DECAY_RATE = 0.01

PENALTY_FLOOD = 0.3
PENALTY_CONTRADICTION = 0.5
PENALTY_CONTAMINATION = 0.4
PENALTY_RAPID_MOD = 0.6

_TRUST_TASK: asyncio.Task[None] | None = None


def decay_rate_for_source(source_type: str) -> float:
    return DECAY_RATE_BY_SOURCE.get(source_type, DEFAULT_DECAY_RATE)


def _hours_since(created_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created_at).total_seconds() / 3600.0)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


_NEGATION_PATTERN = re.compile(
    r"\b(?:not|never|no|isn\'t|isnt|don\'t|dont|doesn\'t|doesnt|won\'t|wont|can\'t|cant)\s+([a-z][a-z0-9_-]{2,})\b",
    re.IGNORECASE,
)


def _extract_negated_terms(text: str) -> list[str]:
    return [m.group(1).lower() for m in _NEGATION_PATTERN.finditer(text)]


def _word_present_positive(mem_content: str, word: str) -> bool:
    low = mem_content.lower()
    if word not in low:
        return False
    for m in re.finditer(r"\b" + re.escape(word) + r"\b", low):
        start = max(0, m.start() - 40)
        prefix = low[start : m.start()]
        if re.search(
            r"\b(?:not|never|no|isn't|isnt|don't|dont|doesn't|doesnt)\s+$",
            prefix,
        ):
            continue
        return True
    return False


def _rapid_modification_flag(timestamps: list[datetime]) -> bool:
    if len(timestamps) <= 5:
        return False
    ts = sorted(timestamps)
    if ts[0].tzinfo is None:
        ts = [t.replace(tzinfo=timezone.utc) for t in ts]
    q: deque[datetime] = deque()
    for t in ts:
        q.append(t)
        while q and (t - q[0]).total_seconds() > 600:
            q.popleft()
        if len(q) > 5:
            return True
    return False


def _build_trust_breakdown(
    *,
    base_score: float,
    time_decay_factor: float,
    source_reliability_factor: float,
    anomaly_penalty: float,
    triggered_rules: list[str],
) -> dict[str, Any]:
    return {
        "base_score": base_score,
        "time_decay_factor": time_decay_factor,
        "source_reliability_factor": source_reliability_factor,
        "anomaly_penalty": anomaly_penalty,
        "triggered_rules": triggered_rules,
        "formula": "base_score * time_decay_factor * source_reliability_factor * anomaly_penalty",
    }


async def run_trust_pass(session: AsyncSession) -> dict[str, Any]:
    """One full recalculation for all non-deleted memories."""
    redis = await get_redis()
    result = await session.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events))
        .where(Memory.is_deleted.is_(False))
    )
    memories: list[Memory] = list(result.scalars().unique().all())

    by_agent_session: dict[tuple[uuid.UUID, uuid.UUID | None], list[Memory]] = defaultdict(list)
    for m in memories:
        by_agent_session[(m.agent_id, m.session_id)].append(m)

    updated = 0
    flagged_new = 0

    for mem in memories:
        evs = sorted(mem.provenance_events, key=lambda e: e.timestamp)
        event_times = [e.timestamp for e in evs]
        if event_times and event_times[0].tzinfo is None:
            event_times = [t.replace(tzinfo=timezone.utc) for t in event_times]

        triggers: list[tuple[str, float, str]] = []

        if mem.session_id is not None:
            wkey = session_writes_cache_key(str(mem.agent_id), str(mem.session_id))
            wcount_raw = await redis.get(wkey)
            wcount = int(wcount_raw) if wcount_raw is not None else 0
            if wcount > 50:
                triggers.append(
                    (
                        "write_rate_flood",
                        PENALTY_FLOOD,
                        f"Session write count {wcount} exceeds 50 (possible flood)",
                    )
                )

        peers = [
            x
            for x in by_agent_session[(mem.agent_id, mem.session_id)]
            if x.id != mem.id
            and not x.is_deleted
            and x.trust_score > 0.7
            and not x.is_flagged
        ]
        neg_terms = _extract_negated_terms(mem.content)
        for term in neg_terms:
            hits = sum(1 for p in peers if _word_present_positive(p.content, term))
            if hits >= 3:
                triggers.append(
                    (
                        "source_inconsistency",
                        PENALTY_CONTRADICTION,
                        f'Negated term "{term}" appears positively in {hits} high-trust peer memories',
                    )
                )
                break

        if mem.session_id is not None:
            fr_key = session_flagged_reads_cache_key(str(mem.agent_id), str(mem.session_id))
            fr_raw = await redis.get(fr_key)
            fr_count = int(fr_raw) if fr_raw is not None else 0
            if fr_count >= 3:
                triggers.append(
                    (
                        "trust_chain_contamination",
                        PENALTY_CONTAMINATION,
                        f"Agent read {fr_count} flagged memories in this session (>=3)",
                    )
                )

        if _rapid_modification_flag(event_times):
            triggers.append(
                (
                    "rapid_modification",
                    PENALTY_RAPID_MOD,
                    "More than 5 provenance events within a 10-minute window",
                )
            )

        anomaly_penalty = 1.0
        rule_names: list[str] = []
        reasons: list[str] = []
        for name, pen, desc in triggers:
            anomaly_penalty *= pen
            rule_names.append(name)
            reasons.append(f"{name}: {desc}")

        dr = decay_rate_for_source(mem.source_type)
        h = _hours_since(mem.created_at)
        time_decay_factor = math.exp(-dr * h)

        needs_flag = len(triggers) > 0
        new_reason = "; ".join(reasons) if needs_flag else None

        if needs_flag:
            if not mem.is_flagged or mem.flag_reason != new_reason:
                mem.is_flagged = True
                mem.flag_reason = new_reason
                await log_memory_event(
                    session,
                    memory_id=mem.id,
                    event_type="anomaly_flagged",
                    performed_by_agent_id=None,
                    event_metadata={
                        "rules": rule_names,
                        "descriptions": reasons,
                    },
                )
                flagged_new += 1

        rel = 0.5 if mem.is_flagged else 1.0
        base_score = 1.0
        new_trust = _clamp01(base_score * time_decay_factor * rel * anomaly_penalty)

        prev = mem.trust_score
        mem.trust_score = new_trust

        breakdown = _build_trust_breakdown(
            base_score=base_score,
            time_decay_factor=time_decay_factor,
            source_reliability_factor=rel,
            anomaly_penalty=anomaly_penalty,
            triggered_rules=rule_names,
        )

        if prev != new_trust:
            await log_memory_event(
                session,
                memory_id=mem.id,
                event_type="trust_updated",
                performed_by_agent_id=None,
                event_metadata={
                    "previous_trust_score": prev,
                    "new_trust_score": new_trust,
                    "source": "trust_engine",
                    "breakdown": breakdown,
                },
            )
            updated += 1

        await redis.set(
            trust_cache_key(str(mem.id)),
            str(mem.trust_score),
            ex=settings.trust_cache_ttl_seconds,
        )

    total = len(memories)
    flagged_total = sum(1 for m in memories if m.is_flagged)
    avg_trust = sum(m.trust_score for m in memories) / total if total else 0.0
    snap = TrustMetricSnapshot(
        recorded_at=datetime.now(timezone.utc),
        avg_trust_score=avg_trust,
        total_memories=total,
        flagged_count=flagged_total,
    )
    session.add(snap)
    await session.commit()

    return {
        "memories_processed": total,
        "updated": updated,
        "newly_flagged_events": flagged_new,
        "avg_trust_score": avg_trust,
        "flagged_count": flagged_total,
    }


async def run_trust_cycle() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        return await run_trust_pass(session)


def start_trust_background_task(
    interval_seconds: int = 60,
    on_error: Callable[[BaseException], None] | None = None,
) -> asyncio.Task[None]:
    global _TRUST_TASK

    async def _loop() -> None:
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    await run_trust_pass(session)
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                if on_error:
                    on_error(e)
                else:
                    await asyncio.sleep(5)

    _TRUST_TASK = asyncio.create_task(_loop())
    return _TRUST_TASK


async def stop_trust_background_task() -> None:
    global _TRUST_TASK
    if _TRUST_TASK is not None:
        _TRUST_TASK.cancel()
        try:
            await _TRUST_TASK
        except asyncio.CancelledError:
            pass
        _TRUST_TASK = None
