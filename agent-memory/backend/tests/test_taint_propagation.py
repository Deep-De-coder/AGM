"""Tests for causal taint propagation — PART 7."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.lib.taint_propagation import (
    DECAY_FACTOR,
    compute_final_taint,
    compute_inherited_taint,
    compute_origin_taint,
)
from backend.models import Agent, Memory
from backend.rules.checker import check_memory_rules
from backend.rules.engine import PREDEFINED_RULES


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _create_agent(db: AsyncSession) -> uuid.UUID:
    agent = Agent(name=f"taint-test-{uuid.uuid4().hex[:6]}", metadata_={})
    db.add(agent)
    await db.flush()
    await db.commit()
    return agent.id


async def _create_memory(
    db: AsyncSession,
    agent_id: uuid.UUID,
    *,
    taint_score: float = 0.0,
    taint_sources: dict | None = None,
) -> Memory:
    mem = Memory(
        content="taint propagation test memory",
        agent_id=agent_id,
        source_type="tool_call",
        source_identifier="test",
        safety_context={},
        taint_score=taint_score,
        taint_sources=taint_sources or {},
    )
    db.add(mem)
    await db.flush()
    await db.commit()
    await db.refresh(mem)
    return mem


# ---------------------------------------------------------------------------
# PART 7 TEST 1 — origin taint by source type
# ---------------------------------------------------------------------------


def test_origin_taint_by_source_type():
    assert abs(compute_origin_taint("user_input", "hello", {}) - 0.7) < 1e-9
    assert abs(compute_origin_taint("tool_call", "hello", {}) - 0.1) < 1e-9


def test_origin_taint_high_stakes_multiplier():
    score = compute_origin_taint("tool_call", "delete all credentials", {})
    assert score == pytest.approx(min(1.0, 0.1 * 1.5))


def test_origin_taint_human_verified_reduction():
    score = compute_origin_taint("user_input", "hello", {"human_verified": True})
    assert score == pytest.approx(0.7 * 0.3)


def test_origin_taint_override():
    score = compute_origin_taint("tool_call", "hello", {"taint_override": 0.95})
    assert score == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# PART 7 TEST 2 — inherited taint propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inherited_taint_propagation(
    async_session_factory, override_db  # noqa: ARG001
):
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)
        parent = await _create_memory(
            db, agent_id, taint_score=0.8, taint_sources={"user_input": 0.8}
        )

        inherited_score, inherited_sources = await compute_inherited_taint(
            [str(parent.id)], db
        )

    expected_contribution = 0.8 * DECAY_FACTOR  # 0.56
    assert inherited_score == pytest.approx(expected_contribution)
    assert "user_input" in inherited_sources
    assert inherited_sources["user_input"] == pytest.approx(0.8 * DECAY_FACTOR)


@pytest.mark.asyncio
async def test_inherited_taint_no_parents(
    async_session_factory, override_db  # noqa: ARG001
):
    async with async_session_factory() as db:
        score, sources = await compute_inherited_taint([], db)
    assert score == 0.0
    assert sources == {}


# ---------------------------------------------------------------------------
# PART 7 TEST 3 — taint decay over depth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taint_decay_over_depth(
    async_session_factory, override_db  # noqa: ARG001
):
    """Taint from A → B → C → D → E → F should be < 0.2 at 5 hops from A."""
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)

        a = await _create_memory(db, agent_id, taint_score=1.0, taint_sources={"user_input": 1.0})
        b_score, b_src = await compute_final_taint(
            "tool_call", "neutral", {}, [str(a.id)], db
        )
        b = await _create_memory(db, agent_id, taint_score=b_score, taint_sources=b_src)

        c_score, c_src = await compute_final_taint(
            "tool_call", "neutral", {}, [str(b.id)], db
        )
        c = await _create_memory(db, agent_id, taint_score=c_score, taint_sources=c_src)

        d_score, d_src = await compute_final_taint(
            "tool_call", "neutral", {}, [str(c.id)], db
        )
        d = await _create_memory(db, agent_id, taint_score=d_score, taint_sources=d_src)

        e_score, e_src = await compute_final_taint(
            "tool_call", "neutral", {}, [str(d.id)], db
        )
        e = await _create_memory(db, agent_id, taint_score=e_score, taint_sources=e_src)

        f_score, _f_src = await compute_final_taint(
            "tool_call", "neutral", {}, [str(e.id)], db
        )

    # After 5 hops from taint=1.0: inherited = 1.0 * 0.7^5 ≈ 0.168
    # tool_call origin = 0.1, so final = max(0.1, 0.168) = 0.168
    assert f_score < 0.2, f"Expected taint < 0.2 at 5 hops, got {f_score}"


# ---------------------------------------------------------------------------
# PART 7 TEST 4 — taint reduces trust
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taint_affects_trust(
    client: AsyncClient, async_session_factory, override_db, fake_redis  # noqa: ARG001
):
    from backend.trust_engine import compute_trust_score

    async with async_session_factory() as db:
        agent_id = await _create_agent(db)
        clean_bare = await _create_memory(db, agent_id, taint_score=0.0)
        tainted_bare = await _create_memory(db, agent_id, taint_score=0.8)

        # Reload with provenance_events eager-loaded so get_utility_multiplier works.
        clean_res = await db.execute(
            select(Memory)
            .options(selectinload(Memory.provenance_events))
            .where(Memory.id == clean_bare.id)
        )
        clean = clean_res.scalar_one()

        tainted_res = await db.execute(
            select(Memory)
            .options(selectinload(Memory.provenance_events))
            .where(Memory.id == tainted_bare.id)
        )
        tainted = tainted_res.scalar_one()

        clean_trust = await compute_trust_score(clean, db, fake_redis)
        tainted_trust = await compute_trust_score(tainted, db, fake_redis)

    assert tainted_trust < clean_trust, (
        f"Tainted memory trust {tainted_trust:.3f} should be < clean trust {clean_trust:.3f}"
    )


# ---------------------------------------------------------------------------
# PART 7 TEST 5 — RULE_014 fires on taint > 0.8
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_014_fires(
    async_session_factory, fake_redis, override_db  # noqa: ARG001
):
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)
        mem = await _create_memory(db, agent_id, taint_score=0.9)

        violations = await check_memory_rules(str(mem.id), db, fake_redis)

    rule_names = [v.rule_name for v in violations]
    assert "RULE_014" in rule_names, f"Expected RULE_014 in violations, got: {rule_names}"


@pytest.mark.asyncio
async def test_rule_014_does_not_fire_below_threshold(
    async_session_factory, fake_redis, override_db  # noqa: ARG001
):
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)
        mem = await _create_memory(db, agent_id, taint_score=0.5)

        violations = await check_memory_rules(str(mem.id), db, fake_redis)

    rule_names = [v.rule_name for v in violations]
    assert "RULE_014" not in rule_names


# ---------------------------------------------------------------------------
# PART 7 TEST 6 — safe memories excludes high taint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_memories_excludes_high_taint(
    client: AsyncClient, async_session_factory, override_db  # noqa: ARG001
):
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)

        high_taint = await _create_memory(db, agent_id, taint_score=0.95)
        low_taint = await _create_memory(db, agent_id, taint_score=0.1)

    resp = await client.get("/memories/safe")
    assert resp.status_code == 200

    ids = [item["id"] for item in resp.json()]
    assert str(high_taint.id) not in ids, "High-taint memory should be excluded from /memories/safe"
    assert str(low_taint.id) in ids, "Low-taint memory should appear in /memories/safe"
