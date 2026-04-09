"""Default behavioral baseline and rolling updates after memory writes."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Agent, Memory

DEFAULT_BEHAVIORAL_BASELINE: dict[str, Any] = {
    "avg_content_length": 200.0,
    "std_content_length": 50.0,
    "avg_writes_per_session": 10.0,
    "std_writes_per_session": 5.0,
    "source_type_distribution": {
        "tool_call": 0.4,
        "user_input": 0.3,
        "inter_agent": 0.2,
        "web_fetch": 0.1,
    },
}

_SOURCE_KEYS = ("tool_call", "user_input", "inter_agent", "web_fetch")
_ALPHA = 0.1


def _normalize_distribution(dist: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(dist.get(k, 0.0))) for k in _SOURCE_KEYS)
    if total <= 0:
        return {k: 0.25 for k in _SOURCE_KEYS}
    return {k: max(0.0, float(dist.get(k, 0.0))) / total for k in _SOURCE_KEYS}


async def update_behavioral_baseline(
    db: AsyncSession, agent_id: Any, new_memory: Memory
) -> None:
    """EMA (alpha=0.1) for content length and source-type distribution."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        return
    base = agent.behavioral_baseline
    if base is None:
        base = copy.deepcopy(DEFAULT_BEHAVIORAL_BASELINE)
    else:
        base = copy.deepcopy(base)

    content_len = float(len(new_memory.content or ""))
    old_avg = float(base.get("avg_content_length", 200.0))
    base["avg_content_length"] = (1.0 - _ALPHA) * old_avg + _ALPHA * content_len

    dist = _normalize_distribution(
        {k: float(base.get("source_type_distribution", {}).get(k, 0.25)) for k in _SOURCE_KEYS}
    )
    st = new_memory.source_type
    for k in _SOURCE_KEYS:
        bump = 1.0 if st == k else 0.0
        dist[k] = (1.0 - _ALPHA) * dist[k] + _ALPHA * bump
    base["source_type_distribution"] = _normalize_distribution(dist)

    agent.behavioral_baseline = base
    await db.flush()
