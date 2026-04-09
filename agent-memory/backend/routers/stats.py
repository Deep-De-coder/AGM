"""Dashboard aggregate metrics and trust history."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.dendritic_cell import DendriticCellAgent, dca_sample_to_dict
from backend.lib.quorum_trust import compute_quorum_score
from backend.models import Agent, Memory, TrustMetricSnapshot
from backend.redis_client import get_redis, ns_key
from backend.schemas import DangerSignalsBlock, DashboardSummary, TrustHistoryPoint
from backend.trust_engine import compute_danger_signals

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Memory)
                .where(Memory.is_deleted.is_(False))
            )
        ).scalar_one()
    )
    flagged = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Memory)
                .where(Memory.is_deleted.is_(False), Memory.is_flagged.is_(True))
            )
        ).scalar_one()
    )
    avg_row = await db.execute(
        select(func.avg(Memory.trust_score)).where(Memory.is_deleted.is_(False))
    )
    avg_raw = avg_row.scalar_one()
    avg_trust = float(avg_raw) if avg_raw is not None else 0.0

    agents = int(
        (await db.execute(select(func.count()).select_from(Agent))).scalar_one()
    )

    by_src_result = await db.execute(
        select(Memory.source_type, func.count())
        .where(Memory.is_deleted.is_(False))
        .group_by(Memory.source_type)
    )
    memories_by_source_type: dict[str, int] = {
        str(st): int(c) for st, c in by_src_result.all()
    }

    ds_raw = await compute_danger_signals(db)
    danger = DangerSignalsBlock(
        anergy_ratio=float(ds_raw["anergy_ratio"]),
        source_diversity_index=float(ds_raw["source_diversity_index"]),
        reasoning_coherence=float(ds_raw["reasoning_coherence"]),
        anergy_threshold_breached=bool(ds_raw["anergy_threshold_breached"]),
        diversity_threshold_breached=bool(ds_raw["diversity_threshold_breached"]),
        coherence_threshold_breached=bool(ds_raw["coherence_threshold_breached"]),
    )

    redis = await get_redis()
    dca_block: dict[str, Any] | None = None
    try:
        raw = await redis.get(ns_key("dca:scan:latest"))
        if raw:
            blob = json.loads(raw)
            samples = blob.get("samples", [])
            last_scan_at = blob.get("sampled_at")
            danger_n = sum(1 for s in samples if s.get("net_context") == "MATURE_DANGER")
            semi_n = sum(1 for s in samples if s.get("net_context") == "SEMI_MATURE")
            safe_n = sum(1 for s in samples if s.get("net_context") == "SAFE")
            dca_block = {
                "last_scan_at": last_scan_at,
                "agents_in_danger": danger_n,
                "agents_semi_mature": semi_n,
                "agents_safe": safe_n,
            }
    except Exception:
        dca_block = {
            "last_scan_at": None,
            "agents_in_danger": 0,
            "agents_semi_mature": 0,
            "agents_safe": 0,
        }

    qh = {"full_quorum_agents": 0, "partial_quorum_agents": 0, "failed_quorum_agents": 0}
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=2)
        aids = (
            await db.execute(
                select(Memory.agent_id)
                .where(Memory.is_deleted.is_(False), Memory.created_at >= since)
                .distinct()
                .limit(100)
            )
        ).all()
        for (aid,) in aids:
            q = await compute_quorum_score(str(aid), None, db, redis)
            if q.quorum_status == "FULL_QUORUM":
                qh["full_quorum_agents"] += 1
            elif q.quorum_status == "PARTIAL_QUORUM":
                qh["partial_quorum_agents"] += 1
            else:
                qh["failed_quorum_agents"] += 1
    except Exception:
        pass

    v_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Memory)
                .where(Memory.is_deleted.is_(False), Memory.content_hash.isnot(None))
            )
        ).scalar_one()
    )
    v_ok = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Memory)
                .where(
                    Memory.is_deleted.is_(False),
                    Memory.content_hash.isnot(None),
                    Memory.content_hash_valid.is_(True),
                )
            )
        ).scalar_one()
    )

    return DashboardSummary(
        total_memories=total,
        flagged_count=flagged,
        average_trust_score=avg_trust,
        active_agents_count=agents,
        memories_by_source_type=memories_by_source_type,
        danger_signals=danger,
        dca=dca_block,
        quorum_health=qh,
        integrity={"verified": v_ok, "total_with_hash": v_total},
    )


@router.get("/dca/{agent_id}")
async def stats_dca_agent(agent_id: str) -> dict[str, Any]:
    import backend.database as database

    redis = await get_redis()
    dca = DendriticCellAgent(database.AsyncSessionLocal, redis)
    s = await dca.get_agent_context(agent_id)
    return dca_sample_to_dict(s)


def _coerce_bucket_ts(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        s = val.strip().replace(" ", "T", 1)
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = datetime.fromisoformat(val)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise TypeError(f"Unexpected bucket type: {type(val)}")


@router.get("/trust-history", response_model=list[TrustHistoryPoint])
async def trust_history(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
) -> list[TrustHistoryPoint]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    bind = db.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        hour_bucket = func.strftime(
            "%Y-%m-%d %H:00:00", TrustMetricSnapshot.created_at
        ).label("bucket")
    else:
        hour_bucket = func.date_trunc("hour", TrustMetricSnapshot.created_at).label(
            "bucket"
        )
    result = await db.execute(
        select(
            hour_bucket,
            func.avg(TrustMetricSnapshot.trust_score).label("average_trust_score"),
            func.count(distinct(TrustMetricSnapshot.memory_id)).label("total_memories"),
        )
        .where(TrustMetricSnapshot.created_at >= since)
        .group_by(hour_bucket)
        .order_by(hour_bucket.asc())
    )
    rows = result.all()
    out: list[TrustHistoryPoint] = []
    for r in rows:
        if r.bucket is None:
            continue
        out.append(
            TrustHistoryPoint(
                timestamp=_coerce_bucket_ts(r.bucket),
                average_trust_score=float(r.average_trust_score),
                total_memories=int(r.total_memories or 0),
            )
        )
    return out
