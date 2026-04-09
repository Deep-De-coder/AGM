"""Administrative operations."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.trust_engine import run_trust_pass

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/run-trust-decay", status_code=status.HTTP_200_OK)
async def run_trust_decay(db: AsyncSession = Depends(get_db)) -> dict[str, int | float]:
    return await run_trust_pass(db)
