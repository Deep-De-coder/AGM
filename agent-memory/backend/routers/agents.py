"""Agent registration and lookup."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Agent, Memory
from backend.schemas import (
    AgentCreate,
    AgentListResponse,
    AgentRegistryRow,
    AgentResponse,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentListResponse)
async def list_agents(
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AgentListResponse:
    not_deleted = Memory.is_deleted.is_(False)
    mem_stats = (
        select(
            Memory.agent_id.label("agent_id"),
            func.count(Memory.id).filter(not_deleted).label("memory_count"),
            func.avg(Memory.trust_score).filter(not_deleted).label("avg_trust"),
            func.sum(
                case((and_(not_deleted, Memory.is_flagged.is_(True)), 1), else_=0)
            ).label("flagged_memory_count"),
        )
        .group_by(Memory.agent_id)
        .subquery()
    )

    total_result = await db.execute(select(func.count()).select_from(Agent))
    total = int(total_result.scalar_one())

    rows_result = await db.execute(
        select(
            Agent.id,
            Agent.name,
            Agent.created_at,
            func.coalesce(mem_stats.c.memory_count, 0).label("memory_count"),
            func.coalesce(mem_stats.c.avg_trust, 0.0).label("avg_trust"),
            func.coalesce(mem_stats.c.flagged_memory_count, 0).label(
                "flagged_memory_count"
            ),
        )
        .outerjoin(mem_stats, Agent.id == mem_stats.c.agent_id)
        .order_by(Agent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = rows_result.all()
    items = [
        AgentRegistryRow(
            id=r.id,
            name=r.name,
            created_at=r.created_at,
            memory_count=int(r.memory_count),
            avg_trust_score=float(r.avg_trust),
            flagged_memory_count=int(r.flagged_memory_count),
        )
        for r in rows
    ]
    return AgentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(
    body: AgentCreate, db: AsyncSession = Depends(get_db)
) -> Agent:
    agent = Agent(name=body.name, metadata_=body.metadata)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return agent
