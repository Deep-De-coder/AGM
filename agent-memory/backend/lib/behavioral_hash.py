"""Rolling behavioral vector + SHA256 fingerprint per agent."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import log_memory_event
from backend.lib.baseline import DEFAULT_BEHAVIORAL_BASELINE
from backend.models import Agent, Memory
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import get_redis

BEHAVIORAL_VECTOR_FIELDS = [
    "avg_content_length",
    "avg_content_length_std",
    "source_type_dist",
    "avg_trust_score_written",
    "write_interval_avg",
    "write_interval_std",
    "session_count",
    "flag_rate",
    "inter_agent_fraction",
    "avg_safety_context_keys",
]

_EPS = 1e-6


def _js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    keys = sorted(set(p.keys()) | set(q.keys()))
    if not keys:
        return 0.0

    p_raw = {k: max(0.0, float(p.get(k, 0.0))) for k in keys}
    q_raw = {k: max(0.0, float(q.get(k, 0.0))) for k in keys}
    sp = sum(p_raw.values())
    sq = sum(q_raw.values())
    if sp <= 0 and sq <= 0:
        return 0.0
    if sp <= 0 or sq <= 0:
        return 1.0

    p_norm = {k: v / sp for k, v in p_raw.items()}
    q_norm = {k: v / sq for k, v in q_raw.items()}
    m = {k: (p_norm[k] + q_norm[k]) / 2.0 for k in keys}

    def _kl(a: dict[str, float], b: dict[str, float]) -> float:
        total = 0.0
        for k in keys:
            av = float(a[k])
            bv = float(b[k])
            if av == 0.0:
                continue
            if bv == 0.0:
                return math.log(2.0)
            total += av * math.log(av / bv)
        return total

    jsd = 0.5 * _kl(p_norm, m) + 0.5 * _kl(q_norm, m)
    normalized = jsd / math.log(2.0)
    return max(0.0, min(1.0, float(normalized)))


def compute_behavioral_vector(agent_id: uuid.UUID, recent_memories: list[Memory]) -> dict[str, Any]:
    if not recent_memories:
        return {
            "avg_content_length": 0.0,
            "avg_content_length_std": 0.0,
            "source_type_dist": {},
            "avg_trust_score_written": 0.0,
            "write_interval_avg": 0.0,
            "write_interval_std": 0.0,
            "session_count": 0.0,
            "flag_rate": 0.0,
            "inter_agent_fraction": 0.0,
            "avg_safety_context_keys": 0.0,
        }
    lens = [len(m.content or "") for m in recent_memories]
    avg_len = statistics.mean(lens)
    std_len = statistics.pstdev(lens) if len(lens) > 1 else 0.0
    st: dict[str, float] = {}
    for m in recent_memories:
        st[m.source_type] = st.get(m.source_type, 0.0) + 1.0
    tot = float(len(recent_memories))
    st = {k: v / tot for k, v in st.items()}
    avg_trust = statistics.mean([float(m.trust_score) for m in recent_memories])
    ts_sorted = sorted(recent_memories, key=lambda x: x.created_at)
    intervals: list[float] = []
    for i in range(1, len(ts_sorted)):
        dt = (ts_sorted[i].created_at - ts_sorted[i - 1].created_at).total_seconds()
        intervals.append(max(0.0, dt))
    wi_avg = statistics.mean(intervals) if intervals else 0.0
    wi_std = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
    return {
        "avg_content_length": float(avg_len),
        "avg_content_length_std": float(std_len),
        "source_type_dist": st,
        "avg_trust_score_written": float(avg_trust),
        "write_interval_avg": float(wi_avg),
        "write_interval_std": float(wi_std),
        "session_count": 0.0,
        "flag_rate": 0.0,
        "inter_agent_fraction": 0.0,
        "avg_safety_context_keys": 0.0,
    }


async def _fill_agent_level_stats(
    db: AsyncSession, agent_id: uuid.UUID, vec: dict[str, Any]
) -> None:
    sc = await db.execute(
        select(func.count(func.distinct(Memory.session_id))).where(
            Memory.agent_id == agent_id,
            Memory.is_deleted.is_(False),
            Memory.session_id.isnot(None),
        )
    )
    vec["session_count"] = float(sc.scalar_one() or 0)
    tot = await db.execute(
        select(func.count()).where(Memory.agent_id == agent_id, Memory.is_deleted.is_(False))
    )
    ntot = int(tot.scalar_one() or 0)
    if ntot <= 0:
        vec["flag_rate"] = 0.0
        vec["inter_agent_fraction"] = 0.0
    else:
        fl = await db.execute(
            select(func.count()).where(
                Memory.agent_id == agent_id,
                Memory.is_deleted.is_(False),
                Memory.is_flagged.is_(True),
            )
        )
        vec["flag_rate"] = float(fl.scalar_one() or 0) / float(ntot)
        ia = await db.execute(
            select(func.count()).where(
                Memory.agent_id == agent_id,
                Memory.is_deleted.is_(False),
                Memory.source_type == "inter_agent",
            )
        )
        vec["inter_agent_fraction"] = float(ia.scalar_one() or 0) / float(ntot)
    res = await db.execute(
        select(Memory.safety_context).where(
            Memory.agent_id == agent_id, Memory.is_deleted.is_(False)
        )
    )
    rows = res.scalars().all()
    if rows:
        keys_sum = sum(len(x or {}) for x in rows)
        vec["avg_safety_context_keys"] = float(keys_sum) / float(len(rows))
    else:
        vec["avg_safety_context_keys"] = 0.0


def hash_behavioral_vector(vector: dict[str, Any]) -> str:
    st = vector.get("source_type_dist") or {}
    payload = {
        "avg_content_length": vector.get("avg_content_length"),
        "avg_content_length_std": vector.get("avg_content_length_std"),
        "source_type_dist": dict(sorted((str(k), float(v)) for k, v in st.items())),
        "avg_trust_score_written": vector.get("avg_trust_score_written"),
        "write_interval_avg": vector.get("write_interval_avg"),
        "write_interval_std": vector.get("write_interval_std"),
        "session_count": vector.get("session_count"),
        "flag_rate": vector.get("flag_rate"),
        "inter_agent_fraction": vector.get("inter_agent_fraction"),
        "avg_safety_context_keys": vector.get("avg_safety_context_keys"),
    }
    s = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_behavioral_drift(current_vector: dict[str, Any], baseline_vector: dict[str, Any]) -> float:
    def nd(c: float, b: float) -> float:
        return abs(float(c) - float(b)) / (abs(float(b)) + _EPS)

    ac = float(current_vector.get("avg_content_length", 0.0))
    bc = float(baseline_vector.get("avg_content_length", ac))
    astd = float(current_vector.get("avg_content_length_std", 0.0))
    bstd = float(baseline_vector.get("avg_content_length_std", astd))
    d_len = (nd(ac, bc) + nd(astd, bstd)) / 2.0

    cd = current_vector.get("source_type_dist") or {}
    bd = baseline_vector.get("source_type_dist") or {}
    if not bd and DEFAULT_BEHAVIORAL_BASELINE.get("source_type_distribution"):
        bd = {
            k: float(v)
            for k, v in DEFAULT_BEHAVIORAL_BASELINE["source_type_distribution"].items()
        }
    d_src = _js_divergence(
        {str(k): float(v) for k, v in cd.items()},
        {str(k): float(v) for k, v in bd.items()},
    )

    wia = float(current_vector.get("write_interval_avg", 0.0))
    wib = float(baseline_vector.get("write_interval_avg", wia))
    wis_c = float(current_vector.get("write_interval_std", 0.0))
    wis_b = float(baseline_vector.get("write_interval_std", wis_c))
    d_wi = (nd(wia, wib) + nd(wis_c, wis_b)) / 2.0

    fr_c = float(current_vector.get("flag_rate", 0.0))
    fr_b = float(baseline_vector.get("flag_rate", fr_c))
    d_fr = nd(fr_c, fr_b)

    rest_keys = (
        "avg_trust_score_written",
        "session_count",
        "inter_agent_fraction",
        "avg_safety_context_keys",
    )
    rest = 0.0
    for k in rest_keys:
        rest += nd(
            float(current_vector.get(k, 0.0)),
            float(baseline_vector.get(k, 0.0)),
        )
    rest /= max(1, len(rest_keys))

    return (
        0.2 * d_len
        + 0.2 * d_src
        + 0.3 * d_wi
        + 0.15 * d_fr
        + 0.15 * rest
    )


def _drifted_fields(
    current_vector: dict[str, Any], baseline_vector: dict[str, Any]
) -> list[str]:
    out: list[str] = []
    for k in (
        "avg_content_length",
        "avg_content_length_std",
        "avg_trust_score_written",
        "write_interval_avg",
        "write_interval_std",
        "session_count",
        "flag_rate",
        "inter_agent_fraction",
        "avg_safety_context_keys",
    ):
        c = float(current_vector.get(k, 0.0))
        b = float(baseline_vector.get(k, 0.0))
        if abs(c - b) / (abs(b) + _EPS) > 0.3:
            out.append(k)
    return out


async def update_agent_behavioral_hash(
    agent_id: uuid.UUID,
    new_memory: Memory,
    db: AsyncSession,
) -> tuple[str, float]:
    res = await db.execute(
        select(Memory)
        .where(Memory.agent_id == agent_id, Memory.is_deleted.is_(False))
        .order_by(Memory.created_at.desc())
        .limit(20)
    )
    recent = list(res.scalars().all())
    vec = compute_behavioral_vector(agent_id, recent)
    await _fill_agent_level_stats(db, agent_id, vec)
    new_hash = hash_behavioral_vector(vec)

    ag_res = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = ag_res.scalar_one()
    baseline = agent.behavioral_vector
    if baseline is None:
        baseline = {
            "avg_content_length": float(
                (agent.behavioral_baseline or DEFAULT_BEHAVIORAL_BASELINE).get(
                    "avg_content_length", 200.0
                )
            ),
            "avg_content_length_std": 0.0,
            "source_type_dist": dict(
                (agent.behavioral_baseline or DEFAULT_BEHAVIORAL_BASELINE).get(
                    "source_type_distribution", {}
                )
            ),
            "avg_trust_score_written": 0.8,
            "write_interval_avg": 60.0,
            "write_interval_std": 30.0,
            "session_count": vec["session_count"],
            "flag_rate": 0.0,
            "inter_agent_fraction": 0.2,
            "avg_safety_context_keys": vec["avg_safety_context_keys"],
        }
    drift = compute_behavioral_drift(vec, baseline)
    old_hash = agent.behavioral_hash
    now = datetime.now(timezone.utc)
    agent.behavioral_vector = vec
    agent.behavioral_hash = new_hash
    agent.behavioral_hash_updated_at = now
    agent.behavioral_drift_score = drift
    await db.flush()

    if drift > 0.4:
        try:
            r = await get_redis()
            await push_notification(
                NotificationEvent(
                    id=str(uuid.uuid4()),
                    type="rule_violation",
                    severity="HIGH",
                    title="Behavioral drift",
                    message=(
                        f"BEHAVIORAL DRIFT: Agent {agent.name} hash changed significantly. "
                        f"Drift score: {drift:.3f}. Possible impersonation."
                    ),
                    memory_id=str(new_memory.id),
                    agent_id=str(agent_id),
                    rule_name="BEHAVIORAL",
                    timestamp=now,
                    read=False,
                ),
                r,
            )
        except Exception:
            pass
        await log_memory_event(
            db,
            memory_id=new_memory.id,
            event_type="anomaly_flagged",
            performed_by_agent_id=agent_id,
            event_metadata={
                "drift_score": drift,
                "old_hash": old_hash,
                "new_hash": new_hash,
                "drifted_fields": _drifted_fields(vec, baseline),
            },
        )

    if drift > 0.05:
        await log_memory_event(
            db,
            memory_id=new_memory.id,
            event_type="behavioral_hash_updated",
            performed_by_agent_id=agent_id,
            event_metadata={
                "old_hash": old_hash,
                "new_hash": new_hash,
                "drift_score": drift,
                "vector_snapshot": vec,
            },
        )

    return new_hash, drift
