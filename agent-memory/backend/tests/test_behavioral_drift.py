"""Behavioral drift score: bounded, and no alarms from cold-start statistics."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.lib.behavioral_hash import _rel_diff, compute_behavioral_drift
from backend.models import MemoryProvenanceLog


def test_rel_diff_is_bounded_and_symmetric() -> None:
    assert _rel_diff(0.0, 0.0) == 0.0
    assert _rel_diff(5.0, 0.0) == 1.0  # used to be 5 / 1e-6
    assert _rel_diff(0.0, 5.0) == 1.0
    assert _rel_diff(2.0, 4.0) == _rel_diff(4.0, 2.0) == 0.5


def test_drift_stays_in_unit_interval_when_baseline_fields_are_zero() -> None:
    current = {
        "avg_content_length": 900.0,
        "avg_content_length_std": 120.0,
        "source_type_dist": {"inter_agent": 1.0},
        "write_interval_avg": 3.0,
        "write_interval_std": 2.0,
        "flag_rate": 0.4,
        "avg_trust_score_written": 0.5,
        "session_count": 3.0,
        "inter_agent_fraction": 1.0,
        "avg_safety_context_keys": 4.0,
    }
    zeros = {k: 0.0 for k in current if k != "source_type_dist"}
    zeros["source_type_dist"] = {"tool_call": 1.0}
    assert 0.0 <= compute_behavioral_drift(current, zeros) <= 1.0


@pytest.mark.asyncio
async def test_first_writes_do_not_raise_drift_alarm(
    client: AsyncClient,
    override_db: None,
    async_session_factory,
) -> None:
    ar = await client.post("/agents", json={"name": "newcomer", "metadata": {}})
    agent_id = ar.json()["id"]
    for i in range(2):
        r = await client.post(
            "/memories",
            json={
                "content": f"short note {i}",
                "agent_id": agent_id,
                "source_type": "tool_call",
                "source_identifier": "t",
                "safety_context": {},
            },
        )
        assert r.status_code == 201

    async with async_session_factory() as s:
        events = (
            await s.execute(
                select(MemoryProvenanceLog).where(
                    MemoryProvenanceLog.event_type == "anomaly_flagged"
                )
            )
        ).scalars().all()
    assert not [e for e in events if "drift_score" in (e.event_metadata or {})]
