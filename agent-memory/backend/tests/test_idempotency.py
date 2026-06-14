"""Tests for idempotency keys on POST /memories — Feature A."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _create_agent(client: AsyncClient) -> str:
    resp = await client.post(
        "/agents",
        json={"name": f"idem-test-{uuid.uuid4().hex[:6]}", "metadata": {}},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# TEST 1 — Explicit idempotency key deduplicates the write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_write_returns_original(
    client: AsyncClient, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent(client)
    key = f"test-idem-{uuid.uuid4().hex[:12]}"

    first = await client.post(
        "/memories",
        json={
            "content": "idempotency test memory",
            "agent_id": agent_id,
            "source_type": "tool_call",
            "source_identifier": "test",
            "safety_context": {"context_hash": "ctx_idem_1"},
        },
        headers={"X-Idempotency-Key": key},
    )
    assert first.status_code == 201
    first_id = first.json()["memory_id"]

    second = await client.post(
        "/memories",
        json={
            "content": "idempotency test memory",
            "agent_id": agent_id,
            "source_type": "tool_call",
            "source_identifier": "test",
            "safety_context": {"context_hash": "ctx_idem_1"},
        },
        headers={"X-Idempotency-Key": key},
    )
    assert second.status_code == 200
    assert second.headers.get("X-Idempotent-Replay") == "true"
    assert second.json()["memory_id"] == first_id


# ---------------------------------------------------------------------------
# TEST 2 — Auto-dedup without explicit key (content hash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_dedup_without_explicit_key(
    client: AsyncClient, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent(client)
    unique_content = f"auto dedup content {uuid.uuid4().hex}"

    body = {
        "content": unique_content,
        "agent_id": agent_id,
        "source_type": "tool_call",
        "source_identifier": "auto_test",
        "safety_context": {"context_hash": "ctx_auto"},
    }

    first = await client.post("/memories", json=body)
    assert first.status_code == 201

    second = await client.post("/memories", json=body)
    assert second.status_code == 200
    assert second.headers.get("X-Idempotent-Replay") == "true"
    assert second.json()["memory_id"] == first.json()["memory_id"]


# ---------------------------------------------------------------------------
# TEST 3 — Different keys create separate memories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_keys_create_separate_memories(
    client: AsyncClient, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent(client)

    first = await client.post(
        "/memories",
        json={
            "content": "memory A",
            "agent_id": agent_id,
            "source_type": "tool_call",
            "source_identifier": "test",
        },
        headers={"X-Idempotency-Key": f"key-a-{uuid.uuid4().hex}"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/memories",
        json={
            "content": "memory B",
            "agent_id": agent_id,
            "source_type": "tool_call",
            "source_identifier": "test",
        },
        headers={"X-Idempotency-Key": f"key-b-{uuid.uuid4().hex}"},
    )
    assert second.status_code == 201
    assert first.json()["memory_id"] != second.json()["memory_id"]


# ---------------------------------------------------------------------------
# TEST 4 — After key is deleted (TTL expired), same request creates a new memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_expires_after_key_deleted(
    client: AsyncClient, fake_redis, override_db  # noqa: ARG001
) -> None:
    agent_id = await _create_agent(client)
    unique_content = f"expiry test {uuid.uuid4().hex}"
    body = {
        "content": unique_content,
        "agent_id": agent_id,
        "source_type": "tool_call",
        "source_identifier": "expire_test",
    }
    key = f"expiry-{uuid.uuid4().hex}"

    first = await client.post("/memories", json=body, headers={"X-Idempotency-Key": key})
    assert first.status_code == 201
    first_id = first.json()["memory_id"]

    # Simulate TTL expiry by deleting the Redis key directly
    await fake_redis.delete(f"idempotency:{key}")

    # Same key now creates a new memory
    second = await client.post("/memories", json=body, headers={"X-Idempotency-Key": key})
    assert second.status_code == 201
    assert second.json()["memory_id"] != first_id
