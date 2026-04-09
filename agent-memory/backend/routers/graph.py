"""Memory / agent graph for React Flow."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Agent, Memory, MemoryProvenanceLog
from backend.schemas import GraphEdge, GraphNode, GraphPayload

router = APIRouter(prefix="/graph", tags=["graph"])


def _trust_color(score: float) -> str:
    if score > 0.7:
        return "#22c55e"
    if score >= 0.4:
        return "#eab308"
    return "#ef4444"


@router.get("", response_model=GraphPayload)
async def get_graph(db: AsyncSession = Depends(get_db)) -> GraphPayload:
    agents_r = await db.execute(select(Agent))
    agents = list(agents_r.scalars().all())

    mem_r = await db.execute(
        select(Memory).where(Memory.is_deleted.is_(False)).options(selectinload(Memory.agent))
    )
    memories = list(mem_r.scalars().all())

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    nodes.append(
        GraphNode(
            id="system:trust",
            kind="system",
            label="Trust engine",
            data={},
        )
    )

    for a in agents:
        nodes.append(
            GraphNode(
                id=f"agent:{a.id}",
                kind="agent",
                label=a.name,
                data={"agent_id": str(a.id), "name": a.name},
            )
        )

    for m in memories:
        mid = f"memory:{m.id}"
        preview = (m.content[:80] + "…") if len(m.content) > 80 else m.content
        nodes.append(
            GraphNode(
                id=mid,
                kind="memory",
                label=preview,
                data={
                    "memory_id": str(m.id),
                    "trust_score": m.trust_score,
                    "is_flagged": m.is_flagged,
                    "color": _trust_color(m.trust_score),
                    "content": m.content,
                    "source_type": m.source_type,
                },
            )
        )
        edges.append(
            GraphEdge(
                id=f"wrote:{m.agent_id}:{m.id}",
                source=f"agent:{m.agent_id}",
                target=mid,
                label="wrote",
                data={"kind": "write"},
            )
        )

    prov_r = await db.execute(select(MemoryProvenanceLog))
    events = list(prov_r.scalars().all())

    for e in events:
        mid = f"memory:{e.memory_id}"
        if e.event_type == "read" and e.performed_by_agent_id is not None:
            edges.append(
                GraphEdge(
                    id=f"read:{e.id}",
                    source=mid,
                    target=f"agent:{e.performed_by_agent_id}",
                    label="read",
                    data={"kind": "read", "timestamp": e.timestamp.isoformat()},
                )
            )
        elif e.event_type in ("trust_updated", "trust_update"):
            aid = e.performed_by_agent_id
            tgt = f"agent:{aid}" if aid is not None else "system:trust"
            edges.append(
                GraphEdge(
                    id=f"trust:{e.id}",
                    source=mid,
                    target=tgt,
                    label="trust_updated",
                    data={
                        "kind": "trust",
                        "event_type": e.event_type,
                        "metadata": e.event_metadata,
                    },
                )
            )

    return GraphPayload(nodes=nodes, edges=edges)
