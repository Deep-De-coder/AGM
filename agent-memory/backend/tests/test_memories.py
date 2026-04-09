"""API tests for memory endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.models import Agent, Memory
from backend.trust_engine import run_trust_pass


@pytest.mark.asyncio
async def test_write_memory_success(
    client: AsyncClient,
    override_db: None,
    async_session_factory,
) -> None:
    ar = await client.post("/agents", json={"name": "writer", "metadata": {}})
    assert ar.status_code == 201
    agent_id = ar.json()["id"]
    body = {
        "content": "hello",
        "agent_id": agent_id,
        "source_type": "user_input",
        "source_identifier": "s1",
        "safety_context": {},
        "session_id": str(uuid.uuid4()),
    }
    r = await client.post("/memories", json=body)
    assert r.status_code == 201
    data = r.json()
    assert "memory_id" in data
    assert data["trust_score"] == 1.0


@pytest.mark.asyncio
async def test_write_memory_missing_agent_returns_404(
    client: AsyncClient, override_db: None
) -> None:
    fake = str(uuid.uuid4())
    r = await client.post(
        "/memories",
        json={
            "content": "x",
            "agent_id": fake,
            "source_type": "user_input",
            "source_identifier": "s",
            "safety_context": {},
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_read_memory_logs_provenance(
    client: AsyncClient, override_db: None
) -> None:
    ar = await client.post("/agents", json={"name": "r", "metadata": {}})
    agent_id = ar.json()["id"]
    wr = await client.post(
        "/memories",
        json={
            "content": "prov",
            "agent_id": agent_id,
            "source_type": "user_input",
            "source_identifier": "s",
            "safety_context": {},
        },
    )
    mid = wr.json()["memory_id"]
    gr = await client.get(f"/memories/{mid}")
    assert gr.status_code == 200
    prov = gr.json().get("provenance", [])
    types = {e["event_type"] for e in prov}
    assert "write" in types
    assert "read" in types


@pytest.mark.asyncio
async def test_query_memories_by_trust_score(
    client: AsyncClient,
    override_db: None,
    async_session_factory,
) -> None:
    ar = await client.post("/agents", json={"name": "q", "metadata": {}})
    agent_id = ar.json()["id"]
    async with async_session_factory() as session:
        low = Memory(
            content="low",
            agent_id=uuid.UUID(agent_id),
            source_type="user_input",
            source_identifier="a",
            safety_context={},
            trust_score=0.2,
        )
        high = Memory(
            content="high",
            agent_id=uuid.UUID(agent_id),
            source_type="user_input",
            source_identifier="b",
            safety_context={},
            trust_score=0.9,
        )
        session.add_all([low, high])
        await session.commit()

    r = await client.get("/memories", params={"min_trust_score": 0.5})
    assert r.status_code == 200
    items = r.json()["items"]
    scores = {it["content"]: it["trust_score"] for it in items}
    assert "high" in scores
    assert "low" not in scores


@pytest.mark.asyncio
async def test_flag_memory_reduces_trust(
    override_db: None,
    async_session_factory,
    fake_redis,
) -> None:
    async with async_session_factory() as session:
        agent = Agent(name="f", metadata_={})
        session.add(agent)
        await session.flush()
        mem = Memory(
            content="flag me",
            agent_id=agent.id,
            source_type="user_input",
            source_identifier="x",
            safety_context={},
            trust_score=1.0,
            is_flagged=True,
            flag_reason="test",
        )
        session.add(mem)
        await session.commit()
        mid = mem.id

    async with async_session_factory() as session:
        result = await session.execute(select(Memory).where(Memory.id == mid))
        m = result.scalar_one()
        before = m.trust_score
        await run_trust_pass(session, manual=True)

    async with async_session_factory() as session:
        result = await session.execute(select(Memory).where(Memory.id == mid))
        m = result.scalar_one()
        assert m.trust_score < before
        assert m.trust_score >= 0.0
