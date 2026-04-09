"""Dashboard aggregate metrics and trust history."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Agent, Memory, TrustMetricSnapshot
from backend.schemas import DashboardSummary, TrustHistoryPoint

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

    return DashboardSummary(
        total_memories=total,
        flagged_count=flagged,
        average_trust_score=avg_trust,
        active_agents_count=agents,
        memories_by_source_type=memories_by_source_type,
    )


@router.get("/trust-history", response_model=list[TrustHistoryPoint])
async def trust_history(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
) -> list[TrustHistoryPoint]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    hour_bucket = func.date_trunc("hour", TrustMetricSnapshot.created_at).label(
        "bucket"
    )
    result = await db.execute(
        select(
            hour_bucket,
            func.avg(TrustMetricSnapshot.trust_score).label("average_trust_score"),
        )
        .where(TrustMetricSnapshot.created_at >= since)
        .group_by(hour_bucket)
        .order_by(hour_bucket.asc())
    )
    rows = result.all()
    return [
        TrustHistoryPoint(
            timestamp=r.bucket,
            average_trust_score=float(r.average_trust_score),
        )
        for r in rows
        if r.bucket is not None
    ]
