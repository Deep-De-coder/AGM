"""Dendritic Cell Agent (DCA): damage-oriented runtime signals (Matzinger-style)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.database import log_memory_event
from backend.models import Memory, MemoryProvenanceLog
from backend.notifications import NotificationEvent, push_notification
from backend.redis_client import ns_key
from backend.trust_engine import _cosine_similarity

SCAN_CACHE_TTL = 90
AGENT_CACHE_TTL = 60
TRUST_DROP_TTL = 600


@dataclass
class DCASample:
    agent_id: str
    danger_score: float
    safe_score: float
    net_context: str
    triggered_dangers: list[str]
    triggered_safes: list[str]
    sampled_at: datetime


class DendriticCellAgent:
    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        redis_client: Any,
    ):
        self.db_factory = db_session_factory
        self.redis = redis_client
        self.safe_signal_weights = {
            "consistent_reasoning": 0.3,
            "low_write_velocity": 0.2,
            "source_diversity": 0.2,
            "corroboration_rate": 0.3,
        }
        self.danger_signal_weights = {
            "reasoning_break": 0.35,
            "write_surge": 0.2,
            "source_collapse": 0.15,
            "trust_cliff_cluster": 0.2,
            "retrieval_anomaly": 0.1,
        }

    async def _db(self) -> AsyncSession:
        return self.db_factory()

    async def sample_agent(self, agent_id: str, session_id: str | None = None) -> DCASample:
        aid = uuid.UUID(agent_id)
        now = datetime.now(timezone.utc)
        async with self.db_factory() as db:
            w60 = await db.execute(
                select(func.count())
                .select_from(Memory)
                .where(
                    Memory.agent_id == aid,
                    Memory.is_deleted.is_(False),
                    Memory.created_at >= now - timedelta(seconds=60),
                )
            )
            writes_60s = int(w60.scalar_one() or 0)
            writes_1m = writes_60s
            last20 = await db.execute(
                select(Memory)
                .where(Memory.agent_id == aid, Memory.is_deleted.is_(False))
                .order_by(Memory.created_at.desc())
                .limit(20)
            )
            mems = list(last20.scalars().all())
            source_types = [m.source_type for m in mems]
            st_set = set(source_types)
            low_write = writes_1m < 5
            write_surge = writes_60s > 10
            source_collapse = len(mems) >= 5 and len(st_set) <= 1
            source_diversity = len(st_set) >= 2

            inter = [m for m in mems if m.source_type == "inter_agent"]
            corroborated = 0
            for m in inter:
                cr = await db.execute(
                    select(func.count())
                    .select_from(MemoryProvenanceLog)
                    .where(
                        MemoryProvenanceLog.memory_id == m.id,
                        MemoryProvenanceLog.event_type == "corroboration",
                    )
                )
                if int(cr.scalar_one() or 0) > 0:
                    corroborated += 1
            corroboration_rate = (corroborated / len(inter)) if inter else 1.0
            cor_ok = corroboration_rate > 0.6

            consistent = False
            reasoning_break = False
            by_sess: dict[uuid.UUID | None, list[Memory]] = {}
            for m in mems:
                by_sess.setdefault(m.session_id, []).append(m)
            for sid, group in by_sess.items():
                if sid is None or len(group) < 2:
                    continue
                group.sort(key=lambda x: x.created_at)
                sims: list[float] = []
                for i in range(len(group) - 1):
                    a = group[i].embedding
                    b = group[i + 1].embedding
                    if a is None or b is None:
                        continue
                    sims.append(_cosine_similarity(list(a), list(b)))
                if sims:
                    if all(s > 0.5 for s in sims):
                        consistent = True
                    if any(s < 0.2 for s in sims):
                        reasoning_break = True

            trust_cliff = False
            try:
                raw = await self.redis.lrange(ns_key(f"dca:trust_drop:{agent_id}"), 0, -1)
                recent_mids: set[str] = set()
                cutoff = now.timestamp() - 60
                for row in raw:
                    try:
                        o = json.loads(row)
                        if float(o.get("ts", 0)) >= cutoff:
                            mid = str(o.get("mid", ""))
                            if mid:
                                recent_mids.add(mid)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                trust_cliff = len(recent_mids) >= 3
            except Exception:
                trust_cliff = False

            since10 = now - timedelta(minutes=10)
            read_rows = await db.execute(
                select(MemoryProvenanceLog.event_metadata, Memory.agent_id)
                .join(Memory, Memory.id == MemoryProvenanceLog.memory_id)
                .where(
                    MemoryProvenanceLog.event_type == "read",
                    MemoryProvenanceLog.performed_by_agent_id == aid,
                    MemoryProvenanceLog.timestamp >= since10,
                )
            )
            rows = list(read_rows.all())
            if session_id:
                rows = [
                    row
                    for row in rows
                    if isinstance(row[0], dict)
                    and str(row[0].get("reader_session_id")) == str(session_id)
                ]
            tr = len(rows)
            sr = sum(1 for _, owner_agent in rows if owner_agent == aid)
            retrieval_anomaly = (tr > 0) and (sr / tr) > 0.8

        dangers: list[str] = []
        safes: list[str] = []
        d_score = 0.0
        s_score = 0.0
        if reasoning_break:
            dangers.append("reasoning_break")
            d_score += self.danger_signal_weights["reasoning_break"]
        if write_surge:
            dangers.append("write_surge")
            d_score += self.danger_signal_weights["write_surge"]
        if source_collapse:
            dangers.append("source_collapse")
            d_score += self.danger_signal_weights["source_collapse"]
        if trust_cliff:
            dangers.append("trust_cliff_cluster")
            d_score += self.danger_signal_weights["trust_cliff_cluster"]
        if retrieval_anomaly:
            dangers.append("retrieval_anomaly")
            d_score += self.danger_signal_weights["retrieval_anomaly"]

        if consistent:
            safes.append("consistent_reasoning")
            s_score += self.safe_signal_weights["consistent_reasoning"]
        if low_write:
            safes.append("low_write_velocity")
            s_score += self.safe_signal_weights["low_write_velocity"]
        if source_diversity:
            safes.append("source_diversity")
            s_score += self.safe_signal_weights["source_diversity"]
        if cor_ok:
            safes.append("corroboration_rate")
            s_score += self.safe_signal_weights["corroboration_rate"]

        if s_score > d_score * 1.5:
            ctx = "SAFE"
        elif d_score > s_score:
            ctx = "MATURE_DANGER"
        else:
            ctx = "SEMI_MATURE"

        sample = DCASample(
            agent_id=agent_id,
            danger_score=d_score,
            safe_score=s_score,
            net_context=ctx,
            triggered_dangers=dangers,
            triggered_safes=safes,
            sampled_at=now,
        )
        return sample

    async def run_population_scan(self) -> list[DCASample]:
        now = datetime.now(timezone.utc)
        async with self.db_factory() as db:
            sub = (
                select(Memory.agent_id)
                .where(
                    Memory.is_deleted.is_(False),
                    Memory.created_at >= now - timedelta(hours=2),
                )
                .distinct()
            )
            res = await db.execute(sub)
            agent_ids = [str(r[0]) for r in res.all()]

        samples: list[DCASample] = []
        for aid in agent_ids:
            s = await self.sample_agent(aid)
            samples.append(s)
            if s.net_context == "MATURE_DANGER":
                async with self.db_factory() as db:
                    flag_since = now - timedelta(minutes=30)
                    q = select(Memory).where(
                        Memory.agent_id == uuid.UUID(aid),
                        Memory.is_deleted.is_(False),
                        Memory.created_at >= flag_since,
                    )
                    rows = await db.execute(q)
                    meta = {
                        "dca_danger_score": s.danger_score,
                        "dca_safe_score": s.safe_score,
                        "triggered_dangers": s.triggered_dangers,
                        "context": s.net_context,
                    }
                    for m in rows.scalars().all():
                        m.is_flagged = True
                        m.flag_reason = (
                            "DCA: MATURE_DANGER context — "
                            + ", ".join(s.triggered_dangers)
                        )
                        await log_memory_event(
                            db,
                            memory_id=m.id,
                            event_type="anomaly_flagged",
                            performed_by_agent_id=uuid.UUID(aid),
                            event_metadata=meta,
                        )
                    await db.commit()
                try:
                    await push_notification(
                        NotificationEvent(
                            id=str(uuid.uuid4()),
                            type="danger_signal",
                            severity="CRITICAL",
                            title="DCA danger",
                            message=(
                                f"DCA DANGER: Agent {aid} context = MATURE_DANGER. "
                                f"Signals: {s.triggered_dangers}. "
                                "Recent memories auto-flagged."
                            ),
                            memory_id="",
                            agent_id=aid,
                            rule_name="DCA",
                            timestamp=now,
                            read=False,
                        ),
                        self.redis,
                    )
                except Exception:
                    pass

        try:
            payload = json.dumps(
                {
                    "sampled_at": now.isoformat(),
                    "samples": [
                        {
                            "agent_id": x.agent_id,
                            "danger_score": x.danger_score,
                            "safe_score": x.safe_score,
                            "net_context": x.net_context,
                            "triggered_dangers": x.triggered_dangers,
                            "triggered_safes": x.triggered_safes,
                        }
                        for x in samples
                    ],
                },
                default=str,
            )
            await self.redis.set(
                ns_key("dca:scan:latest"), payload, ex=SCAN_CACHE_TTL
            )
        except Exception:
            pass
        return samples

    async def get_agent_context(self, agent_id: str) -> DCASample:
        try:
            raw = await self.redis.get(ns_key(f"dca:agent:{agent_id}"))
            if raw:
                o = json.loads(raw)
                return DCASample(
                    agent_id=o["agent_id"],
                    danger_score=float(o["danger_score"]),
                    safe_score=float(o["safe_score"]),
                    net_context=o["net_context"],
                    triggered_dangers=list(o.get("triggered_dangers", [])),
                    triggered_safes=list(o.get("triggered_safes", [])),
                    sampled_at=datetime.fromisoformat(o["sampled_at"]),
                )
        except Exception:
            pass
        try:
            s = await self.sample_agent(agent_id)
        except Exception:
            now = datetime.now(timezone.utc)
            return DCASample(
                agent_id=agent_id,
                danger_score=0.0,
                safe_score=0.0,
                net_context="SAFE",
                triggered_dangers=[],
                triggered_safes=[],
                sampled_at=now,
            )
        try:
            await self.redis.set(
                ns_key(f"dca:agent:{agent_id}"),
                json.dumps(
                    {
                        "agent_id": s.agent_id,
                        "danger_score": s.danger_score,
                        "safe_score": s.safe_score,
                        "net_context": s.net_context,
                        "triggered_dangers": s.triggered_dangers,
                        "triggered_safes": s.triggered_safes,
                        "sampled_at": s.sampled_at.isoformat(),
                    }
                ),
                ex=AGENT_CACHE_TTL,
            )
        except Exception:
            pass
        return s


def dca_sample_to_dict(s: DCASample) -> dict[str, Any]:
    return {
        "agent_id": s.agent_id,
        "danger_score": s.danger_score,
        "safe_score": s.safe_score,
        "net_context": s.net_context,
        "triggered_dangers": s.triggered_dangers,
        "triggered_safes": s.triggered_safes,
        "sampled_at": s.sampled_at.isoformat(),
    }
