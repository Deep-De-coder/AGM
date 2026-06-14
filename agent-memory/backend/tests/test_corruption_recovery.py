"""Tests for silent corruption auto-recovery — Feature B."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Agent, Memory, MemoryProvenanceLog


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _create_agent_via_api(client: AsyncClient) -> str:
    resp = await client.post(
        "/agents",
        json={"name": f"corruption-test-{uuid.uuid4().hex[:6]}", "metadata": {}},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _write_memory_via_api(client: AsyncClient, agent_id: str) -> str:
    resp = await client.post(
        "/memories",
        json={
            "content": "original content before tampering",
            "agent_id": agent_id,
            "source_type": "tool_call",
            "source_identifier": "integrity_test",
            "safety_context": {"context_hash": f"ctx_{uuid.uuid4().hex[:8]}"},
        },
    )
    assert resp.status_code == 201
    return resp.json()["memory_id"]


# ---------------------------------------------------------------------------
# TEST 1 — GET on a tampered memory auto-quarantines it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_quarantine_on_hash_mismatch(
    client: AsyncClient, async_session_factory, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent_via_api(client)
    memory_id = await _write_memory_via_api(client, agent_id)
    memory_uuid = uuid.UUID(memory_id)

    # Tamper the stored content_hash so verification will fail
    async with async_session_factory() as db:
        res = await db.execute(select(Memory).where(Memory.id == memory_uuid))
        mem = res.scalar_one()
        mem.content_hash = "deadbeef" * 8  # wrong 64-char hex
        await db.commit()

    # GET should trigger verify_memory_integrity → B1 auto-quarantine
    get_resp = await client.get(f"/memories/{memory_id}")
    assert get_resp.status_code == 200

    async with async_session_factory() as db:
        res = await db.execute(select(Memory).where(Memory.id == memory_uuid))
        mem = res.scalar_one()

    assert mem.memory_state == "quarantined", (
        f"Expected memory_state='quarantined' after hash mismatch, got '{mem.memory_state}'"
    )
    assert mem.is_flagged is True, "Memory should be flagged after auto-quarantine"


# ---------------------------------------------------------------------------
# TEST 2 — Recovery from memory_created provenance event creates anergic copy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_creates_anergic_copy(
    client: AsyncClient, async_session_factory, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent_via_api(client)
    memory_id = await _write_memory_via_api(client, agent_id)
    memory_uuid = uuid.UUID(memory_id)
    agent_uuid = uuid.UUID(agent_id)

    # Tamper the stored content_hash
    async with async_session_factory() as db:
        res = await db.execute(select(Memory).where(Memory.id == memory_uuid))
        mem = res.scalar_one()
        mem.content_hash = "badf00d0" * 8
        await db.commit()

    # GET triggers B1 quarantine + B2 recovery
    get_resp = await client.get(f"/memories/{memory_id}")
    assert get_resp.status_code == 200

    # A recovered anergic copy should have been created for this agent
    async with async_session_factory() as db:
        res = await db.execute(
            select(Memory).where(
                Memory.agent_id == agent_uuid,
                Memory.memory_state == "anergic",
                Memory.is_deleted.is_(False),
            )
        )
        anergic_mems = list(res.scalars().all())

    assert len(anergic_mems) >= 1, (
        "B2 recovery should have created at least one anergic memory copy"
    )
    recovered = anergic_mems[0]
    assert recovered.content == "original content before tampering"


# ---------------------------------------------------------------------------
# TEST 3 — POST /admin/verify-integrity-and-recover returns correct stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_integrity_and_recover_endpoint(
    client: AsyncClient, async_session_factory, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent_via_api(client)
    # Write two memories: one clean, one tampered
    clean_id = await _write_memory_via_api(client, agent_id)
    tampered_id = await _write_memory_via_api(client, agent_id)
    tampered_uuid = uuid.UUID(tampered_id)

    async with async_session_factory() as db:
        res = await db.execute(select(Memory).where(Memory.id == tampered_uuid))
        mem = res.scalar_one()
        mem.content_hash = "cafebabe" * 8
        await db.commit()

    resp = await client.post("/admin/verify-integrity-and-recover")
    assert resp.status_code == 200
    data = resp.json()

    assert "total_scanned" in data
    assert "passed" in data
    assert "failed" in data
    assert "auto_quarantined" in data
    assert "recovered" in data
    assert "unrecoverable" in data
    assert "scan_completed_at" in data

    assert data["total_scanned"] >= 2
    assert data["failed"] >= 1
    assert data["auto_quarantined"] >= 1
    # recovered >= 1 because the tampered memory has a memory_created provenance event
    assert data["recovered"] >= 1
