"""Trust decay and clamping behaviour."""

from __future__ import annotations


import pytest
from sqlalchemy import select

from backend.models import Agent, Memory
from backend.trust_engine import (
    _clamp01,
    decay_rate_for_source,
    run_trust_pass,
)


def test_tool_call_decays_slower_than_inter_agent() -> None:
    assert decay_rate_for_source("tool_call") < decay_rate_for_source("inter_agent")


@pytest.mark.asyncio
async def test_flagged_memory_has_lower_trust(
    override_db: None,
    async_session_factory,
) -> None:
    async with async_session_factory() as session:
        agent = Agent(name="t", metadata_={})
        session.add(agent)
        await session.flush()
        flagged = Memory(
            content="f",
            agent_id=agent.id,
            source_type="user_input",
            source_identifier="a",
            safety_context={},
            trust_score=1.0,
            is_flagged=True,
            flag_reason="x",
        )
        clean = Memory(
            content="c",
            agent_id=agent.id,
            source_type="user_input",
            source_identifier="b",
            safety_context={},
            trust_score=1.0,
            is_flagged=False,
        )
        session.add_all([flagged, clean])
        await session.commit()
        fid, cid = flagged.id, clean.id

    async with async_session_factory() as session:
        await run_trust_pass(session, manual=True)

    async with async_session_factory() as session:
        rf = (
            await session.execute(select(Memory).where(Memory.id == fid))
        ).scalar_one()
        rc = (
            await session.execute(select(Memory).where(Memory.id == cid))
        ).scalar_one()
        assert rf.trust_score < rc.trust_score


@pytest.mark.asyncio
async def test_trust_score_never_goes_negative(
    override_db: None,
    async_session_factory,
) -> None:
    async with async_session_factory() as session:
        agent = Agent(name="n", metadata_={})
        session.add(agent)
        await session.flush()
        mem = Memory(
            content="neg test",
            agent_id=agent.id,
            source_type="user_input",
            source_identifier="z",
            safety_context={},
            trust_score=0.01,
            is_flagged=True,
            flag_reason="stress",
        )
        session.add(mem)
        await session.commit()

    async with async_session_factory() as session:
        await run_trust_pass(session, manual=True)

    async with async_session_factory() as session:
        rows = (await session.execute(select(Memory))).scalars().all()
        for m in rows:
            assert m.trust_score >= 0.0
            assert m.trust_score <= 1.0


def test_clamp01_bounds() -> None:
    assert _clamp01(-5.0) == 0.0
    assert _clamp01(2.0) == 1.0
    assert _clamp01(0.5) == 0.5
