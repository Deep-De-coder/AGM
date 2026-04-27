"""Memory / agent graph for React Flow — supports 3-D position hints and project filtering."""

from __future__ import annotations

import hashlib
import os

from fastapi import APIRouter, Depends, Query
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


def _node_color(m: Memory) -> str:
    sc = m.safety_context or {}
    if sc.get("node_type") in ("project_file", "project_root", "project_synthesis"):
        return "#06b6d4"  # cyan — project nodes
    depth = int(getattr(m, "causal_depth", 0) or 0)
    if depth == 0:
        return "#eab308"
    if depth >= 4:
        return "#a855f7"
    return _trust_color(m.trust_score)


def _position_hint(m: Memory) -> dict[str, float]:
    depth = int(getattr(m, "causal_depth", 0) or 0)
    sc = m.safety_context or {}
    file_path: str = sc.get("file_path", "")
    directory = os.path.dirname(file_path) if file_path else ""
    y = float(int(hashlib.md5(directory.encode()).hexdigest()[:8], 16) % 100)
    z = float((m.trust_score or 1.0) * 100.0)
    return {"x": float(depth), "y": y, "z": z}


@router.get("", response_model=GraphPayload)
async def get_graph(
    project_name: str | None = Query(default=None, description="Filter to a single project"),
    node_types: str | None = Query(
        default=None,
        description="Comma-separated node types to include: system,agent,memory,project_file",
    ),
    show_3d: bool = Query(default=False, description="Attach x/y/z position hints to nodes"),
    db: AsyncSession = Depends(get_db),
) -> GraphPayload:
    # Parse the requested node-type filter (None ⇒ include everything)
    requested_types: set[str] | None = None
    if node_types is not None:
        requested_types = {t.strip() for t in node_types.split(",") if t.strip()}

    def _want(kind: str) -> bool:
        return requested_types is None or kind in requested_types

    agents_r = await db.execute(select(Agent))
    agents = list(agents_r.scalars().all())

    mem_q = (
        select(Memory)
        .where(Memory.is_deleted.is_(False))
        .options(selectinload(Memory.agent))
    )
    if project_name is not None:
        mem_q = mem_q.where(
            Memory.safety_context["project_name"].astext == project_name
        )
    mem_r = await db.execute(mem_q)
    memories = list(mem_r.scalars().all())

    # Pre-build the set of project-file memory node IDs for edge classification
    project_file_node_ids: set[str] = {
        f"memory:{m.id}"
        for m in memories
        if (m.safety_context or {}).get("node_type") == "project_file"
    }

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # System node
    if _want("system"):
        nodes.append(
            GraphNode(
                id="system:trust",
                kind="system",
                label="Trust engine",
                data={},
            )
        )

    # Agent nodes
    for a in agents:
        if not _want("agent"):
            break
        nodes.append(
            GraphNode(
                id=f"agent:{a.id}",
                kind="agent",
                label=a.name,
                data={"agent_id": str(a.id), "name": a.name},
            )
        )

    # Memory nodes
    for m in memories:
        sc = m.safety_context or {}
        node_type_sc: str | None = sc.get("node_type")

        if node_type_sc == "project_file":
            kind = "project_file"
            shape_hint = "box"
        elif node_type_sc in ("project_root", "project_synthesis"):
            kind = "project_file"  # treated as same visual family
            shape_hint = "box"
        else:
            kind = "memory"
            shape_hint = "sphere"

        if not _want(kind):
            continue

        mid = f"memory:{m.id}"
        preview = (m.content[:80] + "…") if len(m.content) > 80 else m.content
        depth = int(getattr(m, "causal_depth", 0) or 0)
        node_color = _node_color(m)

        node_data: dict = {
            "memory_id": str(m.id),
            "trust_score": m.trust_score,
            "is_flagged": m.is_flagged,
            "color": node_color,
            "content": m.content,
            "source_type": m.source_type,
            "causal_depth": depth,
            "shape_hint": shape_hint,
        }
        if show_3d:
            node_data["position_hint"] = _position_hint(m)

        nodes.append(
            GraphNode(
                id=mid,
                kind=kind,
                label=preview,
                data=node_data,
            )
        )
        edges.append(
            GraphEdge(
                id=f"wrote:{m.agent_id}:{m.id}",
                source=f"agent:{m.agent_id}",
                target=mid,
                label="wrote",
                type="provenance",
                data={"kind": "write"},
            )
        )

    # Causal / dependency edges
    for m in memories:
        mid = f"memory:{m.id}"
        parents = getattr(m, "causal_parents", None) or []
        for pid in parents:
            parent_nid = f"memory:{pid}"
            is_dep = mid in project_file_node_ids and parent_nid in project_file_node_ids
            edges.append(
                GraphEdge(
                    id=f"causal:{pid}:{m.id}",
                    source=parent_nid,
                    target=mid,
                    label="depends_on" if is_dep else "caused",
                    type="depends_on" if is_dep else "causal",
                    data=(
                        {"kind": "depends_on", "style": "solid orange"}
                        if is_dep
                        else {"kind": "causal"}
                    ),
                )
            )

    # Provenance events (read / trust_updated)
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
                    type="provenance",
                    data={
                        "kind": "read",
                        "timestamp": e.timestamp.isoformat(),
                    },
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
                    type="provenance",
                    data={
                        "kind": "trust",
                        "event_type": e.event_type,
                        "metadata": e.event_metadata,
                    },
                )
            )

    return GraphPayload(nodes=nodes, edges=edges)
