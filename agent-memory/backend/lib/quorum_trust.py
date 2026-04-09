"""Multi-timescale quorum trust (fast / medium / slow signals)."""

from __future__ import annotations

import json
import math
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Agent, Memory, MemoryProvenanceLog, RuleViolation
from backend.redis_client import get_redis, ns_key

FAST_HALF_LIFE_MIN = 5.0
MEDIUM_HALF_LIFE_H = 2.0
SLOW_HALF_LIFE_H = 168.0


@dataclass
class QuorumScore:
    agent_id: str
    session_id: str
    fast_signal: float
    medium_signal: float
    slow_signal: float
    composite_score: float
    quorum_status: str
    memory_trust_multiplier: float
    failing_signals: list[str]
    computed_at: datetime


def _exp_decay(val: float, hours: float, half_life_h: float) -> float:
    if half_life_h <= 0:
        return val
    return float(val) * math.exp(-math.log(2) * hours / half_life_h)


def _entropy_source_types(memories: list[Memory]) -> float:
    if not memories:
        return 0.0
    counts: dict[str, int] = {}
    for m in memories:
        counts[m.source_type] = counts.get(m.source_type, 0) + 1
    n = float(len(memories))
    h = 0.0
    for c in counts.values():
        p = c / n
        if p > 0:
            h -= p * math.log2(p)
    return h


async def compute_fast_signal(agent_id: str, redis_client: Any) -> float:
    cache_k = ns_key(f"quorum:fast:{agent_id}")
    try:
        raw = await redis_client.get(cache_k)
        if raw is not None:
            return float(raw)
    except Exception:
        pass
    score = 1.0
    try:
        writes_raw = await redis_client.lrange(ns_key(f"fast:writes:{agent_id}"), 0, -1)
        ts_list = [float(x) for x in writes_raw if x]
    except Exception:
        ts_list = []
    variance = 0.0
    if len(ts_list) >= 2:
        intervals = [ts_list[i] - ts_list[i + 1] for i in range(len(ts_list) - 1)]
        if intervals:
            variance = float(statistics.pvariance(intervals)) if len(intervals) > 1 else 0.0
    baseline = 30.0
    if variance > 2 * baseline:
        score *= 0.6
    try:
        dca_raw = await redis_client.get(ns_key(f"dca:agent:{agent_id}"))
        if dca_raw:
            o = json.loads(dca_raw)
            ctx = o.get("net_context", "")
            if ctx == "MATURE_DANGER":
                score *= 0.2
            elif ctx == "SEMI_MATURE":
                score *= 0.7
    except Exception:
        pass
    now_ts = datetime.now(timezone.utc).timestamp()
    last_write = ts_list[0] if ts_list else now_ts
    minutes_since = max(0.0, (now_ts - last_write) / 60.0)
    score *= math.exp(-math.log(2) * minutes_since / FAST_HALF_LIFE_MIN)
    try:
        await redis_client.set(cache_k, str(score), ex=60)
    except Exception:
        pass
    return max(0.0, min(1.0, score))


async def compute_medium_signal(
    agent_id: str,
    session_id: uuid.UUID | str | None,
    db: AsyncSession,
    redis_client: Any,
) -> float:
    if not session_id:
        return 0.8
    sid_key = str(session_id)
    cache_k = ns_key(f"quorum:medium:{agent_id}:{sid_key}")
    try:
        raw = await redis_client.get(cache_k)
        if raw is not None:
            return float(raw)
    except Exception:
        pass
    sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    res = await db.execute(
        select(Memory).where(
            Memory.agent_id == uuid.UUID(agent_id),
            Memory.session_id == sid,
            Memory.is_deleted.is_(False),
        )
    )
    sess_mems = list(res.scalars().all())
    if len(sess_mems) < 3:
        return 0.8
    score = 1.0
    avg_trust = statistics.mean([float(m.trust_score) for m in sess_mems])
    flag_rate = sum(1 for m in sess_mems if m.is_flagged) / float(len(sess_mems))
    ent = _entropy_source_types(sess_mems)
    mids = [m.id for m in sess_mems]
    if mids:
        rv = await db.execute(
            select(func.count())
            .select_from(RuleViolation)
            .where(
                RuleViolation.agent_id == uuid.UUID(agent_id),
                RuleViolation.memory_id.in_(mids),
            )
        )
        rule_violation_count = int(rv.scalar_one() or 0)
    else:
        rule_violation_count = 0
    if avg_trust < 0.5:
        score *= 0.6
    if flag_rate > 0.2:
        score *= 0.5
    if rule_violation_count > 2:
        score *= 0.7
    if ent > 2.0:
        score *= 0.8
    session_start = min(m.created_at for m in sess_mems)
    if session_start.tzinfo is None:
        session_start = session_start.replace(tzinfo=timezone.utc)
    hours_since = (datetime.now(timezone.utc) - session_start).total_seconds() / 3600.0
    score = _exp_decay(score, hours_since, MEDIUM_HALF_LIFE_H)
    try:
        await redis_client.set(cache_k, str(score), ex=600)
    except Exception:
        pass
    return max(0.0, min(1.0, score))


async def compute_slow_signal(agent_id: str, db: AsyncSession, redis_client: Any) -> float:
    cache_k = ns_key(f"quorum:slow:{agent_id}")
    try:
        raw = await redis_client.get(cache_k)
        if raw is not None:
            return float(raw)
    except Exception:
        pass
    aid = uuid.UUID(agent_id)
    ag = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    if ag is None:
        return 0.5
    tot = await db.execute(
        select(func.count()).where(Memory.agent_id == aid, Memory.is_deleted.is_(False))
    )
    n_mem = int(tot.scalar_one() or 0)
    if n_mem <= 0:
        return 0.5
    fl = await db.execute(
        select(func.count()).where(
            Memory.agent_id == aid, Memory.is_deleted.is_(False), Memory.is_flagged.is_(True)
        )
    )
    lifetime_flag_rate = float(fl.scalar_one() or 0) / float(n_mem)
    avg_t = await db.execute(
        select(func.avg(Memory.trust_score)).where(
            Memory.agent_id == aid, Memory.is_deleted.is_(False)
        )
    )
    lifetime_avg_trust = float(avg_t.scalar_one() or 0.5)
    sess_tot = await db.execute(
        select(func.count(func.distinct(Memory.session_id))).where(
            Memory.agent_id == aid,
            Memory.is_deleted.is_(False),
            Memory.session_id.isnot(None),
        )
    )
    total_sessions = int(sess_tot.scalar_one() or 0)
    sess_ok = await db.execute(
        select(func.count(func.distinct(Memory.session_id))).where(
            Memory.agent_id == aid,
            Memory.is_deleted.is_(False),
            Memory.session_id.isnot(None),
            Memory.trust_score >= 0.6,
        )
    )
    ok_sess = int(sess_ok.scalar_one() or 0)
    session_success_rate = (ok_sess / total_sessions) if total_sessions else 1.0
    drift_rows = await db.execute(
        select(MemoryProvenanceLog.event_metadata).where(
            MemoryProvenanceLog.event_type == "behavioral_hash_updated",
            MemoryProvenanceLog.performed_by_agent_id == aid,
        )
    )
    drifts: list[float] = []
    for (meta,) in drift_rows.all():
        if isinstance(meta, dict) and meta.get("drift_score") is not None:
            try:
                drifts.append(float(meta["drift_score"]))
            except (TypeError, ValueError):
                pass
    behavioral_drift_history = statistics.mean(drifts) if drifts else 0.0
    sev_map = {"CRITICAL": 1.0, "HIGH": 0.5, "MEDIUM": 0.2, "LOW": 0.05}
    viol = await db.execute(
        select(RuleViolation.severity, func.count())
        .where(RuleViolation.agent_id == aid)
        .group_by(RuleViolation.severity)
    )
    wsum = 0.0
    for sev, c in viol.all():
        wsum += sev_map.get(str(sev), 0.1) * int(c)
    violation_severity_score = wsum / float(n_mem)
    score = 1.0
    if lifetime_flag_rate > 0.1:
        score *= 0.7
    if lifetime_avg_trust < 0.6:
        score *= 0.6
    if session_success_rate < 0.5:
        score *= 0.8
    if violation_severity_score > 0.3:
        score *= 0.5
    if behavioral_drift_history > 0.5:
        score *= 0.6
    created = ag.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    hours_since_agent = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
    score = _exp_decay(score, hours_since_agent, SLOW_HALF_LIFE_H)
    score = max(0.1, min(1.0, score))
    try:
        await redis_client.set(cache_k, str(score), ex=3600)
    except Exception:
        pass
    return score


async def compute_quorum_score(
    agent_id: str,
    session_id: uuid.UUID | str | None,
    db: AsyncSession,
    redis_client: Any,
) -> QuorumScore:
    try:
        r = redis_client or await get_redis()
    except Exception:
        r = None
    if r is None:
        return QuorumScore(
            agent_id=agent_id,
            session_id=str(session_id) if session_id else "",
            fast_signal=0.8,
            medium_signal=0.8,
            slow_signal=0.8,
            composite_score=0.8,
            quorum_status="FULL_QUORUM",
            memory_trust_multiplier=1.0,
            failing_signals=[],
            computed_at=datetime.now(timezone.utc),
        )
    fast = await compute_fast_signal(agent_id, r)
    medium = await compute_medium_signal(agent_id, session_id, db, r)
    slow = await compute_slow_signal(agent_id, db, r)
    thr = 0.6
    above = sum(1 for x in (fast, medium, slow) if x > thr)
    failing = []
    if fast <= thr:
        failing.append("fast_signal")
    if medium <= thr:
        failing.append("medium_signal")
    if slow <= thr:
        failing.append("slow_signal")
    if above == 3:
        comp = fast * 0.2 + medium * 0.3 + slow * 0.5
        status = "FULL_QUORUM"
        mult = 1.0
    elif above == 2:
        comp = (fast * medium * slow) ** (1.0 / 3.0)
        status = "PARTIAL_QUORUM"
        mult = 0.7
    else:
        comp = min(fast, medium, slow)
        status = "FAILED_QUORUM"
        mult = 0.3
    return QuorumScore(
        agent_id=agent_id,
        session_id=str(session_id) if session_id else "",
        fast_signal=fast,
        medium_signal=medium,
        slow_signal=slow,
        composite_score=comp,
        quorum_status=status,
        memory_trust_multiplier=mult,
        failing_signals=failing,
        computed_at=datetime.now(timezone.utc),
    )


def quorum_to_dict(q: QuorumScore) -> dict[str, Any]:
    return {
        "agent_id": q.agent_id,
        "session_id": q.session_id,
        "fast_signal": q.fast_signal,
        "medium_signal": q.medium_signal,
        "slow_signal": q.slow_signal,
        "composite_score": q.composite_score,
        "quorum_status": q.quorum_status,
        "memory_trust_multiplier": q.memory_trust_multiplier,
        "failing_signals": q.failing_signals,
        "computed_at": q.computed_at.isoformat(),
    }
