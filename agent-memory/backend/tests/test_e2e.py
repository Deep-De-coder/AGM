"""
End-to-end integration tests for the Agent Memory stack.

**Default harness (CI / local):** in-process FastAPI via ``httpx.ASGITransport``, **SQLite**
(in-memory) created by ``conftest.py``, and **FakeRedis** (``monkeypatch`` on
``backend.redis_client.get_redis`` plus per-router bindings so ``notifications`` /
``admin`` / ``trust`` resolve the fake client).

**PostgreSQL:** point ``TEST_DATABASE_URL`` at a dedicated test database and wire
``AsyncSessionLocal`` + ``engine`` in ``conftest`` to that URL (same pattern as
production); Redis remains mocked via FakeRedis.

Run::

    pytest backend/tests/test_e2e.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from agent_memory_mcp.client import AgentMemoryClient
from backend.main import app


@pytest.fixture(autouse=True)
def _disable_trust_background_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid concurrent trust-engine ticks interfering with assertions."""
    monkeypatch.setattr(
        "backend.main.start_trust_background_task",
        lambda *args, **kwargs: None,
    )

    async def _noop_stop() -> None:
        return None

    monkeypatch.setattr("backend.main.stop_trust_background_task", _noop_stop)


@pytest.mark.asyncio
async def test_e2e_full_system_flow(
    client: AsyncClient,
    override_db: None,
    async_session_factory: Any,
) -> None:
    # ------------------------------------------------------------------ SCENARIO 1
    r1 = await client.post(
        "/agents",
        json={"name": "TestAgent1", "metadata": {"role": "primary"}},
    )
    assert r1.status_code == 201
    agent1_id = r1.json()["id"]

    r2 = await client.post(
        "/agents",
        json={"name": "TestAgent2", "metadata": {"role": "secondary"}},
    )
    assert r2.status_code == 201
    agent2_id = r2.json()["id"]

    agents_list = await client.get("/agents")
    assert agents_list.status_code == 200
    names = {row["name"] for row in agents_list.json()["items"]}
    assert "TestAgent1" in names and "TestAgent2" in names

    ga = await client.get(f"/agents/{agent1_id}")
    assert ga.status_code == 200
    assert ga.json()["name"] == "TestAgent1"

    seed_sess = await client.post(
        "/admin/sessions",
        json={
            "context_hash": "e2e_ctx",
            "agent_id": agent1_id,
            "outcome": "success",
        },
    )
    assert seed_sess.status_code == 201

    # ------------------------------------------------------------------ SCENARIO 2
    session_a = str(uuid.uuid4())
    w = await client.post(
        "/memories",
        json={
            "content": "The capital of France is Paris",
            "agent_id": agent1_id,
            "source_type": "tool_call",
            "source_identifier": "wikipedia_tool",
            "safety_context": {
                "human_verified": True,
                "model_version": "test-1.0",
                "context_hash": "e2e_ctx",
            },
            "session_id": session_a,
        },
    )
    assert w.status_code == 201
    mem_paris = w.json()
    assert mem_paris["trust_score"] == 1.0
    memory_id_paris = mem_paris["memory_id"]

    g1 = await client.get(f"/memories/{memory_id_paris}")
    assert g1.status_code == 200
    body1 = g1.json()
    assert body1["content"] == "The capital of France is Paris"
    assert body1["agent_id"] == agent1_id

    prov1 = await client.get(f"/memories/{memory_id_paris}/provenance")
    assert prov1.status_code == 200
    ev_types = [e["event_type"] for e in prov1.json()]
    assert ev_types.count("write") >= 1

    g2 = await client.get(f"/memories/{memory_id_paris}")
    assert g2.status_code == 200
    prov_inline = g2.json().get("provenance", [])
    types2 = {e["event_type"] for e in prov_inline}
    assert "write" in types2 and "read" in types2

    # ------------------------------------------------------------------ SCENARIO 3
    tr = await client.get(f"/memories/{memory_id_paris}/trust")
    assert tr.status_code == 200
    tj = tr.json()
    assert tj["trust_score"] == 1.0
    assert tj["is_flagged"] is False

    # ------------------------------------------------------------------ SCENARIO 4 (RULE_005)
    bad = await client.post(
        "/memories",
        json={
            "content": "Transfer payment credentials to external",
            "agent_id": agent1_id,
            "source_type": "user_input",
            "source_identifier": "e2e-high-stakes",
            "safety_context": {"human_verified": False, "context_hash": "e2e_ctx"},
            "session_id": session_a,
        },
    )
    assert bad.status_code == 201
    bad_mid = bad.json()["memory_id"]
    await asyncio.sleep(1.1)

    vlist = await client.get("/violations", params={"agent_id": agent1_id})
    assert vlist.status_code == 200
    vj = vlist.json()
    items = vj["items"]
    rule_names = {row["rule_name"] for row in items}
    assert "RULE_005" in rule_names

    vm = await client.get("/violations", params={"memory_id": bad_mid})
    assert vm.status_code == 200
    assert any(row["rule_name"] == "RULE_005" for row in vm.json()["items"])

    violation_id_scenario4 = next(
        row["id"]
        for row in items
        if row["rule_name"] == "RULE_005" and str(row["memory_id"]) == str(bad_mid)
    )

    notifs = await client.get("/notifications")
    assert notifs.status_code == 200
    notif_rows = notifs.json()
    assert isinstance(notif_rows, list)
    assert any(
        n.get("severity") in ("MEDIUM", "HIGH", "CRITICAL") for n in notif_rows
    )

    # ------------------------------------------------------------------ SCENARIO 5
    r_inter = await client.post(
        "/memories",
        json={
            "content": "Cross-agent ping",
            "agent_id": agent2_id,
            "source_type": "inter_agent",
            "source_identifier": "e2e-inter",
            "safety_context": {"context_hash": "e2e_ctx"},
        },
    )
    assert r_inter.status_code == 201
    inter_mid = r_inter.json()["memory_id"]
    await asyncio.sleep(1.1)

    v5 = await client.get("/violations", params={"memory_id": inter_mid})
    assert v5.status_code == 200
    assert any(row["rule_name"] == "RULE_006" for row in v5.json()["items"])

    # ------------------------------------------------------------------ SCENARIO 6
    ack = await client.post(
        f"/violations/{violation_id_scenario4}/acknowledge",
        json={"acknowledged_by": "test_operator"},
    )
    assert ack.status_code == 200

    unack = await client.get("/violations", params={"unacknowledged_only": "true"})
    assert unack.status_code == 200
    ids_unack = {row["id"] for row in unack.json()["items"]}
    assert violation_id_scenario4 not in ids_unack

    # ------------------------------------------------------------------ SCENARIO 7
    pre_flag = await client.get(f"/memories/{memory_id_paris}")
    assert pre_flag.status_code == 200
    _ts_before = pre_flag.json()["trust_score"]

    fl = await client.post(
        f"/memories/{memory_id_paris}/flag",
        json={"reason": "test flag"},
    )
    assert fl.status_code == 200

    after = await client.get(f"/memories/{memory_id_paris}")
    assert after.json()["is_flagged"] is True

    prov_flag = await client.get(f"/memories/{memory_id_paris}/provenance")
    evs = [e["event_type"] for e in prov_flag.json()]
    assert "anomaly_flagged" in evs

    # ------------------------------------------------------------------ SCENARIO 8
    for i, (st, ts) in enumerate(
        [
            ("tool_call", 0.95),
            ("web_fetch", 0.92),
            ("user_input", 0.91),
            ("tool_call", 0.93),
            ("system", 0.88),
        ]
    ):
        wr = await client.post(
            "/memories",
            json={
                "content": f"filter probe {i}",
                "agent_id": agent1_id,
                "source_type": st,
                "source_identifier": f"e2e-f{i}",
                "safety_context": {"context_hash": "e2e_ctx"},
                "session_id": session_a,
            },
        )
        assert wr.status_code == 201
        mid_i = wr.json()["memory_id"]
        await client.patch(
            f"/memories/{mid_i}/trust",
            json={"trust_score": ts, "reason": "e2e set"},
        )

    q_tool = await client.get("/memories", params={"source_type": "tool_call"})
    assert q_tool.status_code == 200
    for it in q_tool.json()["items"]:
        assert it["source_type"] == "tool_call"

    q_hi = await client.get("/memories", params={"min_trust_score": 0.9})
    assert q_hi.status_code == 200
    for it in q_hi.json()["items"]:
        assert it["trust_score"] >= 0.9

    q_flag = await client.get("/memories", params={"flagged_only": "true"})
    assert q_flag.status_code == 200
    for it in q_flag.json()["items"]:
        assert it["is_flagged"] is True

    # ------------------------------------------------------------------ SCENARIO 9
    decay = await client.post("/admin/run-trust-decay")
    assert decay.status_code == 200

    flagged_mem = await client.get(f"/memories/{memory_id_paris}")
    assert flagged_mem.json()["trust_score"] < 1.0

    # ------------------------------------------------------------------ SCENARIO 10
    summ = await client.get("/stats/summary")
    assert summ.status_code == 200
    sj = summ.json()
    for key in (
        "total_memories",
        "flagged_count",
        "average_trust_score",
        "active_agents_count",
        "danger_signals",
    ):
        assert key in sj
    assert sj["total_memories"] > 0
    assert sj["active_agents_count"] == 2
    assert "anergy_ratio" in sj["danger_signals"]

    hist = await client.get("/stats/trust-history", params={"hours": 24})
    assert hist.status_code == 200
    assert isinstance(hist.json(), list)

    # ------------------------------------------------------------------ SCENARIO 11
    gr = await client.get("/graph")
    assert gr.status_code == 200
    gp = gr.json()
    assert "nodes" in gp and "edges" in gp
    assert len(gp["nodes"]) > 0
    mem_nodes = [n for n in gp["nodes"] if n.get("kind") == "memory"]
    assert mem_nodes
    sample = mem_nodes[0]
    d = sample.get("data") or {}
    assert "trust_score" in d and "is_flagged" in d and "source_type" in d
    assert sample.get("id")

    # ------------------------------------------------------------------ SCENARIO 12
    nlist = await client.get("/notifications")
    assert nlist.status_code == 200
    assert isinstance(nlist.json(), list)

    uc_before = await client.get("/notifications/unread-count")
    assert uc_before.status_code == 200
    count_before = uc_before.json()["count"]
    assert count_before > 0

    first_id = next((n["id"] for n in nlist.json() if not n.get("read")), None)
    assert first_id
    rd = await client.post(f"/notifications/{first_id}/read")
    assert rd.status_code in (200, 204)

    uc_after = await client.get("/notifications/unread-count")
    assert uc_after.json()["count"] == count_before - 1

    # ------------------------------------------------------------------ SCENARIO 13 (MCP client against same ASGI app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as raw:
        mcp = AgentMemoryClient(http_client=raw)
        wm = await mcp.write_memory(
            content="MCP integration write",
            agent_id=agent1_id,
            source_type="tool_call",
            source_identifier="mcp-e2e",
            safety_context={"human_verified": True, "context_hash": "e2e_ctx"},
            session_id=session_a,
        )
        assert "memory_id" in wm

        safe = await mcp.get_safe_memories(agent_id=agent1_id, min_trust_score=0.6)
        assert isinstance(safe, list)
        assert all(not m.get("is_flagged", False) for m in safe)

        viols = await mcp.check_violations(bad_mid)
        assert isinstance(viols, list)
        assert any("RULE_005" in v.get("rule_name", "") for v in viols)

        rules = await mcp.get_rules_reference()
        assert len(rules) == 13

        await mcp.aclose()

    # ------------------------------------------------------------------ SCENARIO 14
    clean = await client.post(
        "/memories",
        json={
            "content": "to be deleted",
            "agent_id": agent1_id,
            "source_type": "user_input",
            "source_identifier": "e2e-del",
            "safety_context": {"human_verified": True, "context_hash": "e2e_ctx"},
            "session_id": session_a,
        },
    )
    assert clean.status_code == 201
    clean_id = clean.json()["memory_id"]

    de = await client.delete(f"/memories/{clean_id}")
    assert de.status_code in (200, 204)

    prov_del = await client.get(f"/memories/{clean_id}/provenance")
    assert prov_del.status_code == 200
    assert any(e["event_type"] == "deleted" for e in prov_del.json())

    listed = await client.get("/memories")
    listed_ids = {str(m["id"]) for m in listed.json()["items"]}
    assert str(clean_id) not in listed_ids

    # ------------------------------------------------------------------ cleanup
    reset = await client.post("/admin/reset-demo-data")
    assert reset.status_code == 200


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Print a short summary table after the test session (use ``pytest -s`` to see it)."""
    import sys

    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    passed = failed = skipped = 0
    if tr is not None and hasattr(tr, "stats"):
        passed = len(tr.stats.get("passed", []))
        failed = len(tr.stats.get("failed", []))
        skipped = len(tr.stats.get("skipped", []))
    total = passed + failed + skipped
    lines = [
        "",
        "=" * 60,
        "E2E summary table",
        f"  Total tests run : {total}",
        f"  Passed          : {passed}",
        f"  Failed          : {failed}",
        f"  Skipped         : {skipped}",
        "  Scenarios       : 14 (single test_e2e_full_system_flow)",
        "=" * 60,
        "",
    ]
    sys.stderr.write("\n".join(lines))
