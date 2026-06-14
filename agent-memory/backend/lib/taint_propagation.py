"""Causal taint propagation for agent memories.

Taint represents contamination risk from untrusted sources flowing through
causal memory chains. It decays by DECAY_FACTOR per hop so that after 5
generations (0.7^5 ≈ 0.17) the signal is effectively negligible — poisoning
cannot meaningfully propagate beyond ~5 causal hops.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Memory
from backend.rules.engine import _HIGH_STAKES_KEYWORDS

# Taint dilutes by this factor per causal hop.
# At depth 5: 0.7^5 = 0.168 — below significance threshold.
DECAY_FACTOR = 0.7

_ORIGIN_TAINT_BY_SOURCE: dict[str, float] = {
    "user_input": 0.7,   # direct injection vector — highest risk
    "web_fetch": 0.5,    # external, unverified content
    "inter_agent": 0.4,  # partially trusted relay
    "tool_call": 0.1,    # structured output — lowest risk
}
_DEFAULT_ORIGIN_TAINT = 0.2


def compute_origin_taint(
    source_type: str,
    content: str,
    safety_context: dict[str, Any] | None,
) -> float:
    """Compute taint score at write time based on source type and content."""
    sc = safety_context or {}

    # Allow callers (e.g. MCP tool) to supply an explicit override.
    raw_override = sc.get("taint_override")
    if raw_override is not None:
        try:
            return float(max(0.0, min(1.0, float(raw_override))))
        except (TypeError, ValueError):
            pass

    base = _ORIGIN_TAINT_BY_SOURCE.get(source_type, _DEFAULT_ORIGIN_TAINT)

    if sc.get("human_verified") is True:
        base *= 0.3

    low = content.lower()
    if any(kw in low for kw in _HIGH_STAKES_KEYWORDS):
        base *= 1.5

    return min(1.0, base)


async def compute_inherited_taint(
    causal_parents: list[str],
    db: AsyncSession,
) -> tuple[float, dict[str, float]]:
    """Walk causal_parents and compute taint inherited from upstream memories.

    Returns (inherited_taint_score, taint_sources_dict).
    Uses max, not sum, because taint represents worst-case contamination
    from any single path, not cumulative exposure.
    """
    if not causal_parents:
        return 0.0, {}

    parent_uids: list[uuid.UUID] = []
    for pid in causal_parents:
        try:
            parent_uids.append(uuid.UUID(pid))
        except ValueError:
            continue

    if not parent_uids:
        return 0.0, {}

    res = await db.execute(select(Memory).where(Memory.id.in_(parent_uids)))
    parents = list(res.scalars().all())

    max_inherited = 0.0
    merged_sources: dict[str, float] = {}

    for parent in parents:
        parent_taint = float(getattr(parent, "taint_score", 0.0))
        if parent_taint <= 0.0:
            continue

        contribution = parent_taint * DECAY_FACTOR
        max_inherited = max(max_inherited, contribution)

        parent_sources: dict[str, float] = dict(
            getattr(parent, "taint_sources", None) or {}
        )
        for src, val in parent_sources.items():
            merged_sources[src] = max(
                merged_sources.get(src, 0.0), float(val) * DECAY_FACTOR
            )

    return max_inherited, merged_sources


async def compute_final_taint(
    source_type: str,
    content: str,
    safety_context: dict[str, Any] | None,
    causal_parents: list[str],
    db: AsyncSession,
) -> tuple[float, dict[str, float]]:
    """Combined origin + inherited taint. Call this at write time.

    Returns (final_taint_score, taint_sources_dict).
    """
    origin = compute_origin_taint(source_type, content, safety_context)
    inherited_score, inherited_sources = await compute_inherited_taint(
        causal_parents, db
    )

    final_score = max(origin, inherited_score)

    sources = inherited_sources.copy()
    sources[source_type] = max(sources.get(source_type, 0.0), origin)

    return final_score, sources
