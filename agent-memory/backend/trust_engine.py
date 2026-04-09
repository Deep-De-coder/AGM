"""Trust decay, anomaly detection, memory-state maintenance, and danger signals."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import backend.database as database
from backend.config import get_settings
from backend.database import log_memory_event
from backend.lib.quorum_trust import compute_quorum_score
from backend.models import (
    Memory,
    MemoryProvenanceLog,
    Session,
    TrustMetricSnapshot,
)
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import (
    get_redis,
    ns_key,
    session_flagged_reads_cache_key,
    session_outcome_cache_key,
    session_writes_cache_key,
    trust_cache_key,
)

settings = get_settings()
logger = logging.getLogger(__name__)

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
_TRUST_LOOP_ITERATION = 0

_SOURCE_TYPES_ENTROPY = ("tool_call", "user_input", "inter_agent", "web_fetch")


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


def get_reality_score_factor(memory: Memory) -> float:
    sc = memory.safety_context or {}
    raw = sc.get("reality_score")
    if raw is None:
        return 1.0
    try:
        rs = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if rs >= 0.9:
        return 1.0
    if rs >= 0.7:
        return 0.9
    if rs >= 0.5:
        return 0.6
    return 0.3


def get_utility_multiplier(memory: Memory, session_outcome: str | None) -> float:
    """Session outcome: success / failed from ``sessions.outcome`` or Redis fallback."""
    evs = memory.provenance_events or []
    has_read = any(e.event_type == "read" for e in evs)
    if not has_read:
        return 0.8
    if session_outcome == "success":
        return 1.2
    if session_outcome == "failed":
        return 0.6
    return 1.0


def _compute_trust_score_components(
    mem: Memory,
    *,
    time_decay_factor: float,
    source_reliability_factor: float,
    anomaly_penalty: float,
    session_outcome: str | None,
) -> float:
    """Combine exponential decay with utility and reality multipliers (decay math unchanged)."""
    base_score = 1.0
    u = get_utility_multiplier(mem, session_outcome)
    r = get_reality_score_factor(mem)
    return _clamp01(
        base_score
        * time_decay_factor
        * source_reliability_factor
        * anomaly_penalty
        * u
        * r
    )


async def compute_trust_score(memory: Memory, db: AsyncSession, redis: Any) -> float:
    """Lightweight on-read trust recomputation without writing snapshots."""
    dr = decay_rate_for_source(memory.source_type)
    h = _hours_since(memory.created_at)
    time_decay_factor = math.exp(-dr * h)
    source_reliability_factor = 0.5 if memory.is_flagged else 1.0
    anomaly_penalty = 1.0
    session_outcome = await _session_outcome_for_memory(db, redis, memory)
    trust = _compute_trust_score_components(
        memory,
        time_decay_factor=time_decay_factor,
        source_reliability_factor=source_reliability_factor,
        anomaly_penalty=anomaly_penalty,
        session_outcome=session_outcome,
    )
    q = await compute_quorum_score(str(memory.agent_id), memory.session_id, db, redis)
    return _clamp01(trust * q.memory_trust_multiplier)


def _build_trust_breakdown(
    *,
    base_score: float,
    time_decay_factor: float,
    source_reliability_factor: float,
    anomaly_penalty: float,
    utility_multiplier: float,
    reality_score_factor: float,
    triggered_rules: list[str],
) -> dict[str, Any]:
    return {
        "base_score": base_score,
        "time_decay_factor": time_decay_factor,
        "source_reliability_factor": source_reliability_factor,
        "anomaly_penalty": anomaly_penalty,
        "utility_multiplier": utility_multiplier,
        "reality_score_factor": reality_score_factor,
        "triggered_rules": triggered_rules,
        "formula": (
            "base_score * time_decay_factor * source_reliability_factor * "
            "anomaly_penalty * utility_multiplier * reality_score_factor"
        ),
    }


async def _session_outcome_for_memory(
    db: AsyncSession, redis: Any, memory: Memory
) -> str | None:
    if memory.session_id is None:
        return None
    sid = str(memory.session_id)
    res = await db.execute(select(Session.outcome).where(Session.id == memory.session_id))
    row = res.scalar_one_or_none()
    if row is not None and row:
        return str(row)
    raw = await redis.get(session_outcome_cache_key(sid))
    return str(raw) if raw else None


async def _load_session_outcomes(
    db: AsyncSession, redis: Any, memories: list[Memory]
) -> dict[uuid.UUID, str | None]:
    sids = {m.session_id for m in memories if m.session_id is not None}
    if not sids:
        return {}
    res = await db.execute(select(Session.id, Session.outcome).where(Session.id.in_(sids)))
    from_db = {row[0]: (str(row[1]) if row[1] else None) for row in res.all()}
    out: dict[uuid.UUID, str | None] = {}
    for sid in sids:
        if sid in from_db and from_db[sid]:
            out[sid] = from_db[sid]
        else:
            raw = await redis.get(session_outcome_cache_key(str(sid)))
            out[sid] = str(raw) if raw else None
    return out


def determine_initial_memory_state(memory_data: dict[str, Any]) -> str:
    if memory_data.get("source_type") == "inter_agent":
        return "anergic"
    sc = memory_data.get("safety_context") or {}
    raw = sc.get("reality_score")
    try:
        if raw is not None and float(raw) < 0.3:
            return "anergic"
    except (TypeError, ValueError):
        pass
    return "active"


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _agent_has_high_trust_memory(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    q = (
        select(func.count())
        .select_from(Memory)
        .where(
            Memory.agent_id == agent_id,
            Memory.is_deleted.is_(False),
            Memory.trust_score > 0.8,
        )
    )
    n = int((await db.execute(q)).scalar_one() or 0)
    return n > 0


async def promote_anergic_memories(db: AsyncSession) -> int:
    """Promote anergic memories corroborated by 3+ distinct trusted agents."""
    res = await db.execute(
        select(Memory).where(Memory.memory_state == "anergic", Memory.is_deleted.is_(False))
    )
    anergic = list(res.scalars().all())
    promoted = 0
    for mem in anergic:
        prov = await db.execute(
            select(MemoryProvenanceLog).where(
                MemoryProvenanceLog.memory_id == mem.id,
                MemoryProvenanceLog.event_type == "corroboration",
            )
        )
        events = list(prov.scalars().all())
        agent_ids: set[uuid.UUID] = set()
        for e in events:
            aid = e.performed_by_agent_id
            if aid is None:
                continue
            if await _agent_has_high_trust_memory(db, aid):
                agent_ids.add(aid)
        if len(agent_ids) < 3:
            continue
        mem.memory_state = "active"
        await log_memory_event(
            db,
            memory_id=mem.id,
            event_type="state_changed",
            performed_by_agent_id=None,
            event_metadata={
                "from": "anergic",
                "to": "active",
                "reason": "corroboration",
            },
        )
        promoted += 1
    return promoted


async def quarantine_contradicting_memories(db: AsyncSession) -> int:
    res = await db.execute(
        select(Memory).where(
            Memory.memory_state == "anergic",
            Memory.is_deleted.is_(False),
            Memory.embedding.isnot(None),
        )
    )
    anergic_list = list(res.scalars().all())
    quarantined = 0
    for amem in anergic_list:
        emb = amem.embedding
        if emb is None:
            continue
        emb_lit = _vector_literal(list(emb))
        sql = text(
            "SELECT id FROM memories WHERE memory_state = 'active' "
            "AND trust_score > 0.7 AND embedding IS NOT NULL "
            "AND embedding <=> CAST(:emb AS vector) < 0.15 LIMIT 3"
        )
        r2 = await db.execute(sql, {"emb": emb_lit})
        rows = list(r2.fetchall())
        if len(rows) < 3:
            continue
        amem.memory_state = "quarantined"
        amem.is_flagged = True
        amem.flag_reason = "Contradicts 3+ active high-trust memories"
        await log_memory_event(
            db,
            memory_id=amem.id,
            event_type="state_changed",
            performed_by_agent_id=None,
            event_metadata={
                "from": "anergic",
                "to": "quarantined",
                "reason": "contradiction",
            },
        )
        quarantined += 1
    return quarantined


async def consolidate_memories(db: AsyncSession) -> int:
    """Mark stable high-trust active memories as consolidated."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    res = await db.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events))
        .where(
            Memory.memory_state == "active",
            Memory.trust_score > 0.8,
            Memory.created_at < cutoff,
            Memory.is_deleted.is_(False),
        )
    )
    candidates = list(res.scalars().unique().all())
    consolidated = 0
    redis = await get_redis()
    for mem in candidates:
        evs = mem.provenance_events or []
        if not any(e.event_type == "read" for e in evs):
            continue
        oc = await _session_outcome_for_memory(db, redis, mem)
        if oc != "success":
            continue
        mem.memory_state = "consolidated"
        await log_memory_event(
            db,
            memory_id=mem.id,
            event_type="state_changed",
            performed_by_agent_id=None,
            event_metadata={
                "from": "active",
                "to": "consolidated",
                "reason": "high_trust_utility",
            },
        )
        consolidated += 1
    return consolidated


async def compute_danger_signals(db: AsyncSession) -> dict[str, Any]:
    redis = await get_redis()
    total_q = await db.execute(
        select(func.count()).select_from(Memory).where(Memory.is_deleted.is_(False))
    )
    total_count = int(total_q.scalar_one() or 0)
    an_q = await db.execute(
        select(func.count())
        .select_from(Memory)
        .where(Memory.is_deleted.is_(False), Memory.memory_state == "anergic")
    )
    anergic_count = int(an_q.scalar_one() or 0)
    anergy_ratio = (anergic_count / total_count) if total_count else 0.0

    src_rows = await db.execute(
        select(Memory.source_type, func.count())
        .where(Memory.is_deleted.is_(False))
        .group_by(Memory.source_type)
    )
    counts_map: dict[str, int] = {k: 0 for k in _SOURCE_TYPES_ENTROPY}
    for st, c in src_rows.all():
        if st in counts_map:
            counts_map[st] = int(c)
    total_src = sum(counts_map.values()) or 1
    entropy = 0.0
    for k in _SOURCE_TYPES_ENTROPY:
        p = counts_map[k] / total_src
        if p > 0:
            entropy -= p * math.log2(p)
    max_h = math.log2(4)
    source_diversity_index = entropy / max_h if max_h > 0 else 0.0

    emb_res = await db.execute(
        select(Memory)
        .where(Memory.is_deleted.is_(False), Memory.embedding.isnot(None))
        .order_by(Memory.created_at.desc())
        .limit(100)
    )
    last100 = list(emb_res.scalars().all())
    by_session: dict[uuid.UUID | None, list[Memory]] = defaultdict(list)
    for m in last100:
        by_session[m.session_id].append(m)
    sims: list[float] = []
    for sid, group in by_session.items():
        if sid is None or len(group) < 2:
            continue
        group.sort(key=lambda x: x.created_at)
        for i in range(len(group) - 1):
            a = group[i].embedding
            b = group[i + 1].embedding
            if a is None or b is None:
                continue
            sims.append(_cosine_similarity(list(a), list(b)))
    reasoning_coherence = sum(sims) / len(sims) if sims else 1.0

    anergy_threshold_breached = anergy_ratio > 0.4
    diversity_threshold_breached = source_diversity_index < 0.3
    coherence_threshold_breached = reasoning_coherence < 0.3

    if anergy_threshold_breached:
        await push_notification(
            NotificationEvent(
                id=str(uuid.uuid4()),
                type="danger_signal",
                severity="CRITICAL",
                title="Danger signal: anergy ratio",
                message=(
                    f"DANGER: Anergy ratio {anergy_ratio:.1%} — "
                    "high accumulation of unvalidated memories"
                ),
                memory_id="",
                agent_id="",
                rule_name="DANGER_ANERGY",
                timestamp=datetime.now(timezone.utc),
                read=False,
            ),
            redis,
        )
    if diversity_threshold_breached:
        await push_notification(
            NotificationEvent(
                id=str(uuid.uuid4()),
                type="danger_signal",
                severity="HIGH",
                title="Danger signal: source diversity",
                message=(
                    f"DANGER: Source diversity index {source_diversity_index:.2f} — "
                    "memory store dominated by single source type"
                ),
                memory_id="",
                agent_id="",
                rule_name="DANGER_DIVERSITY",
                timestamp=datetime.now(timezone.utc),
                read=False,
            ),
            redis,
        )
    if coherence_threshold_breached:
        await push_notification(
            NotificationEvent(
                id=str(uuid.uuid4()),
                type="danger_signal",
                severity="CRITICAL",
                title="Danger signal: reasoning coherence",
                message=(
                    f"DANGER: Reasoning coherence {reasoning_coherence:.2f} — "
                    "incoherent memory injection detected"
                ),
                memory_id="",
                agent_id="",
                rule_name="DANGER_COHERENCE",
                timestamp=datetime.now(timezone.utc),
                read=False,
            ),
            redis,
        )

    return {
        "anergy_ratio": anergy_ratio,
        "source_diversity_index": source_diversity_index,
        "reasoning_coherence": reasoning_coherence,
        "anergy_threshold_breached": anergy_threshold_breached,
        "diversity_threshold_breached": diversity_threshold_breached,
        "coherence_threshold_breached": coherence_threshold_breached,
    }


async def run_trust_pass(
    session: AsyncSession, *, manual: bool = False
) -> dict[str, Any]:
    """One full recalculation for all non-deleted memories."""
    redis = await get_redis()
    result = await session.execute(
        select(Memory)
        .options(selectinload(Memory.provenance_events))
        .where(Memory.is_deleted.is_(False))
    )
    memories: list[Memory] = list(result.scalars().unique().all())

    outcome_map = await _load_session_outcomes(session, redis, memories)

    by_agent_session: dict[tuple[uuid.UUID, uuid.UUID | None], list[Memory]] = (
        defaultdict(list)
    )
    for m in memories:
        by_agent_session[(m.agent_id, m.session_id)].append(m)

    updated = 0
    flagged_new = 0
    quorum_cache: dict[tuple[str, str | None], Any] = {}

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
            fr_key = session_flagged_reads_cache_key(
                str(mem.agent_id), str(mem.session_id)
            )
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
        soc = outcome_map.get(mem.session_id) if mem.session_id else None
        utility_mult = get_utility_multiplier(mem, soc)
        reality_mult = get_reality_score_factor(mem)
        new_trust = _compute_trust_score_components(
            mem,
            time_decay_factor=time_decay_factor,
            source_reliability_factor=rel,
            anomaly_penalty=anomaly_penalty,
            session_outcome=soc,
        )

        qkey = (str(mem.agent_id), str(mem.session_id) if mem.session_id else None)
        if qkey not in quorum_cache:
            quorum_cache[qkey] = await compute_quorum_score(
                str(mem.agent_id), mem.session_id, session, redis
            )
        q = quorum_cache[qkey]
        new_trust = _clamp01(new_trust * q.memory_trust_multiplier)

        prev = mem.trust_score
        mem.trust_score = new_trust

        if prev - new_trust > 0.3:
            try:
                drop_key = ns_key(f"dca:trust_drop:{mem.agent_id}")
                await redis.lpush(
                    drop_key,
                    json.dumps(
                        {
                            "ts": datetime.now(timezone.utc).timestamp(),
                            "mid": str(mem.id),
                        }
                    ),
                )
                await redis.ltrim(drop_key, 0, 49)
                await redis.expire(drop_key, 600)
            except Exception:
                logger.debug("dca trust_drop record failed", exc_info=True)

        breakdown = _build_trust_breakdown(
            base_score=base_score,
            time_decay_factor=time_decay_factor,
            source_reliability_factor=rel,
            anomaly_penalty=anomaly_penalty,
            utility_multiplier=utility_mult,
            reality_score_factor=reality_mult,
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

        if manual:
            snap_reason = "manual_trigger"
        elif needs_flag:
            snap_reason = "anomaly_detected"
        else:
            snap_reason = "scheduled_decay"
        session.add(
            TrustMetricSnapshot(
                memory_id=mem.id,
                trust_score=new_trust,
                time_decay_factor=time_decay_factor,
                source_reliability_factor=rel,
                anomaly_penalty=anomaly_penalty,
                snapshot_reason=snap_reason,
                quorum_fast_signal=q.fast_signal,
                quorum_medium_signal=q.medium_signal,
                quorum_slow_signal=q.slow_signal,
                quorum_status=q.quorum_status,
            )
        )

    total = len(memories)
    flagged_total = sum(1 for m in memories if m.is_flagged)
    avg_trust = sum(m.trust_score for m in memories) / total if total else 0.0
    await session.commit()

    return {
        "memories_processed": total,
        "updated": updated,
        "newly_flagged_events": flagged_new,
        "avg_trust_score": avg_trust,
        "flagged_count": flagged_total,
    }


async def run_trust_cycle() -> dict[str, Any]:
    async with database.AsyncSessionLocal() as session:
        return await run_trust_pass(session, manual=False)


async def _run_post_trust_maintenance() -> None:
    async def _one(name: str, fn: Any) -> int:
        try:
            async with database.AsyncSessionLocal() as db:
                n = await fn(db)
                await db.commit()
                return int(n)
        except Exception:
            logger.exception("%s failed", name)
            return 0

    n_prom = await _one("promote_anergic_memories", promote_anergic_memories)
    logger.info("promote_anergic_memories: %s", n_prom)
    n_quar = await _one("quarantine_contradicting_memories", quarantine_contradicting_memories)
    logger.info("quarantine_contradicting_memories: %s", n_quar)
    n_cons = await _one("consolidate_memories", consolidate_memories)
    logger.info("consolidate_memories: %s", n_cons)
    try:
        async with database.AsyncSessionLocal() as db:
            sig = await compute_danger_signals(db)
            logger.info("compute_danger_signals: %s", sig)
    except Exception:
        logger.exception("compute_danger_signals failed")


def start_trust_background_task(
    interval_seconds: int = 60,
    on_error: Callable[[BaseException], None] | None = None,
) -> asyncio.Task[None]:
    global _TRUST_TASK, _TRUST_LOOP_ITERATION

    async def _loop() -> None:
        global _TRUST_LOOP_ITERATION
        while True:
            try:
                async with database.AsyncSessionLocal() as session:
                    await run_trust_pass(session, manual=False)
                await _run_post_trust_maintenance()
                _TRUST_LOOP_ITERATION += 1
                if _TRUST_LOOP_ITERATION % 3 == 0:
                    try:
                        from backend.dendritic_cell import DendriticCellAgent

                        redis = await get_redis()
                        dca = DendriticCellAgent(database.AsyncSessionLocal, redis)
                        samples = await dca.run_population_scan()
                        danger_count = sum(
                            1 for s in samples if s.net_context == "MATURE_DANGER"
                        )
                        logger.info(
                            "DCA scan complete: %s agents sampled, %s in MATURE_DANGER context",
                            len(samples),
                            danger_count,
                        )
                    except Exception:
                        logger.exception("DCA scan failed")
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


def start_trust_engine(
    interval_seconds: int = 60,
    on_error: Callable[[BaseException], None] | None = None,
) -> asyncio.Task[None]:
    """Start the periodic trust-decay background loop (app lifespan)."""
    return start_trust_background_task(
        interval_seconds=interval_seconds,
        on_error=on_error,
    )
