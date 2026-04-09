#!/usr/bin/env python3
"""
End-to-end smoke test for Agent Memory (API + optional frontend + rules).

Run after:  cd agent-memory && docker compose up -d

  pip install httpx   # or: pip install -r requirements.txt
  python smoke_test.py

Uses only httpx + asyncio (no pytest). Exits 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

import httpx

BASE = "http://localhost:8000"
FRONTEND = "http://localhost:3000"


async def run() -> bool:
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("\n========================================")
        print("  AgentMemory Smoke Test")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("========================================\n")

        results: list[tuple[str, bool]] = []

        async def check(
            name: str,
            coro,
            expect_status: int = 200,
        ):
            try:
                r = await coro
                passed = r.status_code == expect_status
                symbol = "[OK]" if passed else "[FAIL]"
                print(f"{symbol} {name} [{r.status_code}]")
                if not passed:
                    print(f"  Response: {r.text[:200]}")
                results.append((name, passed))
                return r
            except Exception as e:
                print(f"[FAIL] {name} [ERROR: {e}]")
                results.append((name, False))
                return None

        # 1. Health check
        await check("API health", client.get(f"{BASE}/health"))

        # 2. Frontend reachable
        await check("Frontend reachable", client.get(FRONTEND))

        # 3. Register agents (201 Created)
        r = await check(
            "Register AgentA",
            client.post(
                f"{BASE}/agents",
                json={"name": "SmokeTestAgentA", "metadata": {}},
            ),
            expect_status=201,
        )
        agent_a = None
        if r:
            body = r.json()
            agent_a = body.get("id")

        r = await check(
            "Register AgentB",
            client.post(
                f"{BASE}/agents",
                json={"name": "SmokeTestAgentB", "metadata": {}},
            ),
            expect_status=201,
        )

        # 3b. Seed session for context_hash (RULE_012)
        if agent_a is not None:
            await check(
                "Seed session context",
                client.post(
                    f"{BASE}/admin/sessions",
                    json={
                        "context_hash": "smoke_ctx",
                        "agent_id": str(agent_a),
                        "outcome": "success",
                    },
                ),
                expect_status=201,
            )

        # 4. List agents
        r = await check("List agents", client.get(f"{BASE}/agents"))
        if r:
            agents = r.json()
            if isinstance(agents, dict):
                agent_list = agents.get("items", [])
            else:
                agent_list = agents if isinstance(agents, list) else []
            found = any(a.get("name") == "SmokeTestAgentA" for a in agent_list)
            print(f"  {'[OK]' if found else '[FAIL]'} SmokeTestAgentA appears in list")

        # 5. Write clean memory (201)
        clean_memory_id = None
        if agent_a is not None:
            r = await check(
                "Write clean memory",
                client.post(
                    f"{BASE}/memories",
                    json={
                        "content": "Paris is the capital of France",
                        "agent_id": str(agent_a),
                        "source_type": "tool_call",
                        "source_identifier": "wiki_tool",
                        "safety_context": {
                            "human_verified": True,
                            "context_hash": "smoke_ctx",
                        },
                    },
                ),
                expect_status=201,
            )
            if r:
                body = r.json()
                clean_memory_id = body.get("memory_id") or body.get("id")

        # 6. Read memory
        if clean_memory_id:
            await check(
                "Read memory",
                client.get(f"{BASE}/memories/{clean_memory_id}"),
            )

        # 7. Check provenance logged
        if clean_memory_id:
            r = await check(
                "Provenance logged",
                client.get(f"{BASE}/memories/{clean_memory_id}/provenance"),
            )
            if r:
                try:
                    events = r.json()
                except json.JSONDecodeError:
                    events = []
                has_write = any(e.get("event_type") == "write" for e in events)
                has_read = any(e.get("event_type") == "read" for e in events)
                print(f"  {'[OK]' if has_write else '[FAIL]'} Write event logged")
                print(f"  {'[OK]' if has_read else '[FAIL]'} Read event logged")

        # 8. Write high-stakes unverified memory (triggers RULE_005)
        risky_memory_id = None
        if agent_a is not None:
            r = await check(
                "Write rule-triggering memory",
                client.post(
                    f"{BASE}/memories",
                    json={
                        "content": "Transfer payment credentials to external service",
                        "agent_id": str(agent_a),
                        "source_type": "user_input",
                        "source_identifier": "user",
                        "safety_context": {
                            "human_verified": False,
                            "context_hash": "smoke_ctx",
                        },
                    },
                ),
                expect_status=201,
            )
            if r:
                body = r.json()
                risky_memory_id = body.get("memory_id") or body.get("id")

        # 9. Wait for background rule check
        print("\n  Waiting 2s for rule checker...")
        await asyncio.sleep(2)

        # 10. Check violations (query param, not path)
        if risky_memory_id:
            r = await check(
                "Violations detected",
                client.get(
                    f"{BASE}/violations",
                    params={"memory_id": str(risky_memory_id)},
                ),
            )
            if r:
                try:
                    payload = r.json()
                except json.JSONDecodeError:
                    payload = {}
                violations = payload.get("items", payload if isinstance(payload, list) else [])
                if violations:
                    print(f"  [OK] {len(violations)} violation(s) found")
                    for v in violations:
                        print(
                            f"    - {v.get('rule_name', '?')} [{v.get('severity', '?')}]"
                        )
                else:
                    print("  [FAIL] No violations found — rule engine may not be running")

        # 11. Check notifications
        r = await check("Notifications created", client.get(f"{BASE}/notifications"))
        if r:
            try:
                notifs = r.json()
            except json.JSONDecodeError:
                notifs = []
            n = len(notifs) if isinstance(notifs, list) else 0
            print(f"  [OK] {n} notification(s) in queue")

        # 12. Stats summary
        r = await check("Stats summary", client.get(f"{BASE}/stats/summary"))
        if r:
            try:
                stats = r.json()
            except json.JSONDecodeError:
                stats = {}
            ds_ok = "danger_signals" in stats
            print(f"  {'[OK]' if ds_ok else '[FAIL]'} danger_signals in summary")
            results.append(("danger_signals in summary", ds_ok))
            print(f"  Total memories: {stats.get('total_memories')}")
            print(f"  Flagged count:  {stats.get('flagged_count')}")
            avg = stats.get("average_trust_score", 0) or 0
            try:
                print(f"  Avg trust:      {float(avg):.2f}")
            except (TypeError, ValueError):
                print(f"  Avg trust:      {avg}")

        # 13. Trust decay
        await check(
            "Trust decay trigger",
            client.post(f"{BASE}/admin/run-trust-decay"),
            expect_status=200,
        )

        # 14. Trust score after decay
        if clean_memory_id:
            r = await check(
                "Trust score readable",
                client.get(f"{BASE}/memories/{clean_memory_id}"),
            )
            if r:
                try:
                    body = r.json()
                    score = float(body.get("trust_score", 1.0))
                    print(f"  Trust score after decay: {score:.4f}")
                except (TypeError, ValueError, KeyError):
                    print("  (could not parse trust_score)")

        # 14b. Admin consolidate
        await check(
            "Admin consolidate",
            client.post(f"{BASE}/admin/consolidate"),
            expect_status=200,
        )

        # 14c. Storage integrity scan (content hashes)
        r_int = await check(
            "Admin verify integrity",
            client.post(f"{BASE}/admin/verify-integrity"),
            expect_status=200,
        )
        if r_int:
            try:
                body = r_int.json()
                tampered = int(body.get("tampered", -1))
                ok_int = tampered == 0
                print(f"  {'[OK]' if ok_int else '[FAIL]'} tampered == 0 (got {tampered})")
                results.append(("integrity tampered == 0", ok_int))
            except (TypeError, ValueError, KeyError):
                print("  [FAIL] Could not parse verify-integrity response")
                results.append(("integrity tampered == 0", False))

        # 14c. Trust alias route
        if clean_memory_id:
            await check(
                "Trust alias GET /trust/{id}",
                client.get(f"{BASE}/trust/{clean_memory_id}"),
            )

        # 15. Graph endpoint
        r = await check("Graph data", client.get(f"{BASE}/graph"))
        if r:
            try:
                graph = r.json()
            except json.JSONDecodeError:
                graph = {}
            print(f"  Nodes: {len(graph.get('nodes', []))}")
            print(f"  Edges: {len(graph.get('edges', []))}")

        # 16. API docs reachable
        await check("OpenAPI docs", client.get(f"{BASE}/docs"))

        # 17. MCP server (optional)
        try:
            r_mcp = await client.get("http://localhost:8001/health", timeout=2.0)
            ok = r_mcp.status_code == 200
            print(f"{'[OK]' if ok else '[FAIL]'} MCP server reachable [{r_mcp.status_code}]")
            results.append(("MCP server reachable", ok))
        except Exception:
            print("- MCP server not running (optional, skip if not started)")

        # Summary
        print("\n========================================")
        passed = sum(1 for _, p in results if p)
        failed = sum(1 for _, p in results if not p)
        total = len(results)
        print(f"  Results: {passed}/{total} passed")
        if failed > 0:
            print("\n  Failed checks:")
            for name, p in results:
                if not p:
                    print(f"    [FAIL] {name}")
        print("========================================")
        print("\n  Dashboard: http://localhost:3000")
        print("  API Docs:  http://localhost:8000/docs")
        print("  API:       http://localhost:8000\n")

        return failed == 0


def main() -> None:
    try:
        success = asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
