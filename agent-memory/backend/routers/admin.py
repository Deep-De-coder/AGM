"""Administrative operations."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import (
    Agent,
    Memory,
    MemoryProvenanceLog,
    RuleViolation,
    TrustMetricSnapshot,
)
from backend.notifications import NOTIFICATIONS_LIST_KEY, NOTIFICATIONS_READ_SET_KEY
from backend.redis_client import get_redis
from backend.trust_engine import run_trust_pass

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/run-trust-decay", status_code=status.HTTP_200_OK)
async def run_trust_decay(db: AsyncSession = Depends(get_db)) -> dict[str, int | float]:
    return await run_trust_pass(db, manual=True)


@router.post("/reset-demo-data", status_code=status.HTTP_200_OK)
async def reset_demo_data(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Delete all agents, memories, and related rows; clear session/trust Redis keys."""
    await db.execute(delete(MemoryProvenanceLog))
    await db.execute(delete(RuleViolation))
    await db.execute(delete(TrustMetricSnapshot))
    await db.execute(delete(Memory))
    await db.execute(delete(Agent))
    await db.commit()

    redis = await get_redis()
    for pattern in (
        "writes:*",
        "flagged_reads:*",
        "trust:*",
        "rule_violations:memory:*",
    ):
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
    await redis.delete(NOTIFICATIONS_LIST_KEY)
    await redis.delete(NOTIFICATIONS_READ_SET_KEY)

    return {"status": "ok", "message": "All demo data cleared."}
