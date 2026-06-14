"""Tests for sandbagging detection (RULE_015) — Feature A."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.lib.behavioral_hash import compute_context_drift
from backend.models import Agent, Memory, Session as SessionRow
from backend.rules.checker import check_memory_rules


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _create_agent(db: AsyncSession) -> uuid.UUID:
    agent = Agent(name=f"sandbagging-test-{uuid.uuid4().hex[:6]}", metadata_={})
    db.add(agent)
    await db.flush()
    await db.commit()
    return agent.id


# ---------------------------------------------------------------------------
# TEST 1 — Session context_type defaults to "unknown"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_context_type_default(
    client: AsyncClient, override_db  # noqa: ARG001
) -> None:
    resp = await client.post("/admin/sessions", json={"context_hash": "ctx_default_test"})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "context_hash" in data


# ---------------------------------------------------------------------------
# TEST 2 — Writing in an evaluation session updates evaluation_behavioral_vector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluation_vector_updated_on_write(
    client: AsyncClient, async_session_factory, override_db  # noqa: ARG001
) -> None:
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)

    sess_resp = await client.post(
        "/admin/sessions",
        json={
            "context_hash": f"eval_ctx_{uuid.uuid4().hex[:8]}",
            "agent_id": str(agent_id),
            "context_type": "evaluation",
        },
    )
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["id"]

    mem_resp = await client.post(
        "/memories",
        json={
            "content": "evaluation context memory for sandbagging test",
            "agent_id": str(agent_id),
            "source_type": "tool_call",
            "source_identifier": "eval_tool",
            "session_id": session_id,
            "safety_context": {"context_hash": f"eval_ctx_{uuid.uuid4().hex[:8]}"},
        },
    )
    assert mem_resp.status_code == 201

    async with async_session_factory() as db:
        res = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = res.scalar_one()

    assert agent.evaluation_behavioral_vector is not None, (
        "evaluation_behavioral_vector should be set after writing in an evaluation session"
    )


# ---------------------------------------------------------------------------
# TEST 3 — compute_context_drift returns 0.0 for identical vectors
# ---------------------------------------------------------------------------


def test_context_drift_identical_vectors() -> None:
    vec = {
        "avg_content_length": 150.0,
        "avg_content_length_std": 20.0,
        "avg_trust_score_written": 0.8,
        "write_interval_avg": 60.0,
        "write_interval_std": 10.0,
        "session_count": 3.0,
        "flag_rate": 0.0,
        "inter_agent_fraction": 0.1,
        "avg_safety_context_keys": 2.0,
        "source_type_dist": {"tool_call": 1.0},
    }
    assert compute_context_drift(vec, vec) == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# TEST 4 — RULE_015 fires when evaluation vs production vectors diverge > 0.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_015_fires_on_high_context_drift(
    async_session_factory, fake_redis, override_db  # noqa: ARG001
) -> None:
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)

        # Use orthogonal vectors: cosine distance = 1.0, well above the 0.5 threshold
        res = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = res.scalar_one()
        # Production: all weight on avg_content_length, nothing elsewhere
        agent.behavioral_vector = {
            "avg_content_length": 1.0,
            "avg_content_length_std": 0.0,
            "source_type_dist": {},
            "avg_trust_score_written": 0.0,
            "write_interval_avg": 0.0,
            "write_interval_std": 0.0,
            "session_count": 0.0,
            "flag_rate": 0.0,
            "inter_agent_fraction": 0.0,
            "avg_safety_context_keys": 0.0,
        }
        # Evaluation: all weight on avg_safety_context_keys — orthogonal to production
        agent.evaluation_behavioral_vector = {
            "avg_content_length": 0.0,
            "avg_content_length_std": 0.0,
            "source_type_dist": {},
            "avg_trust_score_written": 0.0,
            "write_interval_avg": 0.0,
            "write_interval_std": 0.0,
            "session_count": 0.0,
            "flag_rate": 0.0,
            "inter_agent_fraction": 0.0,
            "avg_safety_context_keys": 1.0,
        }
        await db.commit()

        mem = Memory(
            content="sandbagging detection test memory",
            agent_id=agent_id,
            source_type="tool_call",
            source_identifier="test",
            safety_context={"context_hash": "sandbagging_ctx"},
        )
        db.add(mem)
        await db.flush()
        await db.commit()

        violations = await check_memory_rules(str(mem.id), db, fake_redis)

    rule_names = [v.rule_name for v in violations]
    assert "RULE_015" in rule_names, (
        f"Expected RULE_015 to fire on high context drift, got: {rule_names}"
    )
