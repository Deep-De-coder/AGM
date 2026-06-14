"""Tests for crash recovery checkpointing — Feature B."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.lib.checkpoint import clear_checkpoint, load_checkpoint, save_checkpoint
from backend.lib.content_address import compute_content_hash
from backend.models import Agent, Memory, TrustMetricSnapshot
from backend.trust_engine import run_trust_pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _create_agent(db: AsyncSession) -> uuid.UUID:
    agent = Agent(name=f"cp-test-{uuid.uuid4().hex[:6]}", metadata_={})
    db.add(agent)
    await db.flush()
    await db.commit()
    return agent.id


async def _create_memory(db: AsyncSession, agent_id: uuid.UUID, content: str) -> uuid.UUID:
    mem = Memory(
        content=content,
        agent_id=agent_id,
        source_type="tool_call",
        source_identifier="cp_test",
        safety_context={},
    )
    db.add(mem)
    await db.flush()
    mem.content_hash = compute_content_hash(
        {
            "content": mem.content,
            "agent_id": mem.agent_id,
            "session_id": mem.session_id,
            "source_type": mem.source_type,
            "source_identifier": mem.source_identifier,
            "created_at": mem.created_at,
        }
    )
    mem.content_hash_valid = True
    await db.commit()
    return mem.id


# ---------------------------------------------------------------------------
# TEST 1 — Save and load a checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_save_and_load(fake_redis) -> None:
    state = {"last_processed_id": str(uuid.uuid4()), "processed_count": 42}
    await save_checkpoint(fake_redis, "trust_decay", state)
    loaded = await load_checkpoint(fake_redis, "trust_decay")
    assert loaded == state


# ---------------------------------------------------------------------------
# TEST 2 — Clear removes the checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_clear(fake_redis) -> None:
    await save_checkpoint(fake_redis, "trust_decay", {"key": "value"})
    await clear_checkpoint(fake_redis, "trust_decay")
    result = await load_checkpoint(fake_redis, "trust_decay")
    assert result is None


# ---------------------------------------------------------------------------
# TEST 3 — Trust decay resumes from checkpoint, skipping earlier memories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_decay_resumes_from_checkpoint(
    async_session_factory, fake_redis, override_db  # noqa: ARG001
) -> None:
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)

    memory_ids: list[uuid.UUID] = []
    for i in range(10):
        async with async_session_factory() as db:
            mid = await _create_memory(db, agent_id, f"checkpoint test memory {i}")
            memory_ids.append(mid)

    # Sort ascending by UUID value — same ordering trust_pass uses
    memory_ids.sort()

    # Pretend the first 5 were already processed; checkpoint sits at #5's id
    fifth_id = memory_ids[4]
    await save_checkpoint(fake_redis, "trust_decay", {
        "last_processed_id": str(fifth_id),
        "processed_count": 5,
    })

    # Trust pass should only process memories 6-10 (5 memories)
    async with async_session_factory() as db:
        await run_trust_pass(db, manual=False)

    async with async_session_factory() as db:
        result = await db.execute(select(TrustMetricSnapshot))
        snapshots = list(result.scalars().all())

    assert len(snapshots) == 5, (
        f"Expected 5 snapshots (memories 6-10), got {len(snapshots)}"
    )


# ---------------------------------------------------------------------------
# TEST 4 — Double-decay guard prevents re-processing within 120 seconds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_double_decay(
    async_session_factory, fake_redis, override_db  # noqa: ARG001
) -> None:
    async with async_session_factory() as db:
        agent_id = await _create_agent(db)
        await _create_memory(db, agent_id, "double decay test memory")

    # First run: creates 1 TrustMetricSnapshot
    async with async_session_factory() as db:
        await run_trust_pass(db, manual=False)

    # Second run: double-decay guard sees the "scheduled_decay" snapshot from
    # the first run (within 120s) and skips all memories
    async with async_session_factory() as db:
        await run_trust_pass(db, manual=False)

    async with async_session_factory() as db:
        result = await db.execute(select(TrustMetricSnapshot))
        snapshots = list(result.scalars().all())

    assert len(snapshots) == 1, (
        f"Expected 1 snapshot after double run (guard should block second), got {len(snapshots)}"
    )
