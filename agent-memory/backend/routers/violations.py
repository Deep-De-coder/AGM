"""Rule violation listing (rule_violations table) and acknowledgement."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Agent, utcnow
from backend.models import RuleViolation as RuleViolationORM
from backend.schemas import RuleViolationResponse, ViolationAcknowledgeBody

router = APIRouter(prefix="/violations", tags=["violations"])


async def _resolve_agent_uuid(db: AsyncSession, raw: str) -> uuid.UUID:
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


def _filters(
    *,
    severity: str | None,
    agent_uuid: uuid.UUID | None,
    rule_name: str | None,
    unacknowledged_only: bool,
    memory_id: uuid.UUID | None = None,
) -> list[Any]:
    cond: list[Any] = []
    if severity:
        cond.append(RuleViolationORM.severity == severity)
    if agent_uuid is not None:
        cond.append(RuleViolationORM.agent_id == agent_uuid)
    if rule_name:
        cond.append(RuleViolationORM.rule_name == rule_name)
    if unacknowledged_only:
        cond.append(RuleViolationORM.is_acknowledged.is_(False))
    if memory_id is not None:
        cond.append(RuleViolationORM.memory_id == memory_id)
    return cond


def _row_to_payload(
    row: RuleViolationORM, agent_name: str | None
) -> dict[str, Any]:
    base = RuleViolationResponse.model_validate(row)
    return base.model_dump(mode="json") | {"agent_name": agent_name}


@router.get("")
async def list_violations(
    severity: str | None = Query(default=None),
    agent_id: str | None = Query(
        default=None,
        description="Agent UUID or registered name.",
    ),
    rule_name: str | None = Query(default=None),
    unacknowledged_only: bool = Query(default=False),
    memory_id: uuid.UUID | None = Query(
        default=None,
        description="Filter to violations for this memory id.",
    ),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List violations from ``rule_violations`` with optional filters."""
    agent_uuid: uuid.UUID | None = None
    if agent_id:
        agent_uuid = await _resolve_agent_uuid(db, agent_id)

    cond = _filters(
        severity=severity,
        agent_uuid=agent_uuid,
        rule_name=rule_name,
        unacknowledged_only=unacknowledged_only,
        memory_id=memory_id,
    )

    count_stmt = select(func.count()).select_from(RuleViolationORM)
    if cond:
        count_stmt = count_stmt.where(*cond)
    total = int((await db.execute(count_stmt)).scalar_one())

    list_stmt = (
        select(RuleViolationORM, Agent.name)
        .outerjoin(Agent, RuleViolationORM.agent_id == Agent.id)
    )
    if cond:
        list_stmt = list_stmt.where(*cond)
    list_stmt = (
        list_stmt.order_by(RuleViolationORM.detected_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(list_stmt)
    items = [
        _row_to_payload(r, name) for r, name in result.all()
    ]

    return {"items": items, "total": total}


@router.get("/{memory_id}")
async def violations_for_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """All violations for a given memory id (path = memory UUID)."""
    cond = _filters(
        severity=None,
        agent_uuid=None,
        rule_name=None,
        unacknowledged_only=False,
        memory_id=memory_id,
    )
    stmt = select(RuleViolationORM, Agent.name).outerjoin(
        Agent, RuleViolationORM.agent_id == Agent.id
    )
    if cond:
        stmt = stmt.where(*cond)
    stmt = stmt.order_by(RuleViolationORM.detected_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    items = [_row_to_payload(r, name) for r, name in rows]
    return {"items": items, "total": len(items)}


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
    await db.refresh(row)
    return {"acknowledged": True, "violation_id": str(violation_id)}
