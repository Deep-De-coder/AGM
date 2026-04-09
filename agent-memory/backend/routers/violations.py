"""Rule violation listing (DB) and acknowledgement."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Agent
from backend.models import RuleViolation as RuleViolationORM
from backend.models import utcnow
from backend.schemas import RuleViolationResponse, ViolationAcknowledgeBody

router = APIRouter(prefix="/violations", tags=["violations"])


async def _resolve_agent_id(db: AsyncSession, raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        pass
    r = await db.execute(select(Agent).where(Agent.name == raw))
    a = r.scalar_one_or_none()
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No agent with id or name {raw!r}",
        )
    return a.id


@router.get("", response_model=None)
async def list_violations(
    memory_id: uuid.UUID | None = Query(
        default=None,
        description="When set, only violations for this memory.",
    ),
    agent_id: str | None = Query(
        default=None,
        description="Filter by agent UUID or registered name (e.g. MaliciousAgent).",
    ),
    group_by_severity: bool = Query(
        default=True,
        description="Include counts grouped by severity.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List persisted violations; optional filters by memory and/or agent."""
    q = select(RuleViolationORM).order_by(RuleViolationORM.detected_at.desc())
    if memory_id is not None:
        q = q.where(RuleViolationORM.memory_id == memory_id)
    if agent_id is not None:
        aid = await _resolve_agent_id(db, agent_id)
        q = q.where(RuleViolationORM.agent_id == aid)

    result = await db.execute(q)
    rows = list(result.scalars().all())

    items = [RuleViolationResponse.model_validate(r) for r in rows]
    out: dict[str, Any] = {
        "items": [i.model_dump(mode="json") for i in items],
        "total": len(items),
    }
    if group_by_severity:
        by_sev: dict[str, int] = defaultdict(int)
        for r in rows:
            by_sev[r.severity] += 1
        out["by_severity"] = dict(by_sev)
    return out


@router.post("/{violation_id}/acknowledge", status_code=status.HTTP_200_OK)
async def acknowledge_violation(
    violation_id: uuid.UUID,
    body: ViolationAcknowledgeBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await db.execute(
        select(RuleViolationORM).where(RuleViolationORM.id == violation_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found"
        )

    row.is_acknowledged = True
    row.acknowledged_by = body.acknowledged_by
    row.acknowledged_at = utcnow()
    await db.commit()
    return {"acknowledged": True, "violation_id": str(violation_id)}
