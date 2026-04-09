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
                select(func.count()).select_from(Memory).where(Memory.is_deleted.is_(False))
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

    agents = int((await db.execute(select(func.count()).select_from(Agent))).scalar_one())

    return DashboardSummary(
        total_memories=total,
        flagged_memories=flagged,
        avg_trust_score=avg_trust,
        active_agents=agents,
    )


@router.get("/trust-history", response_model=list[TrustHistoryPoint])
async def trust_history(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
) -> list[TrustHistoryPoint]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(TrustMetricSnapshot)
        .where(TrustMetricSnapshot.recorded_at >= since)
        .order_by(TrustMetricSnapshot.recorded_at.asc())
    )
    rows = result.scalars().all()
    return [
        TrustHistoryPoint(
            recorded_at=r.recorded_at,
            avg_trust_score=r.avg_trust_score,
            total_memories=r.total_memories,
            flagged_count=r.flagged_count,
        )
        for r in rows
    ]
