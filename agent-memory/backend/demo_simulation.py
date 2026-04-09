"""
Demo: register agents, seed memories, flood a session, run trust decay.

Run from the `agent-memory` directory (so `backend` is importable as a package):

  Windows (PowerShell):
    $env:PYTHONPATH = "$PWD"; python backend/demo_simulation.py

  macOS / Linux:
    PYTHONPATH=. python backend/demo_simulation.py

Requires the API reachable at MEMORY_API_URL (default http://localhost:8000).
"""

from __future__ import annotations

import os
import time
import uuid

import httpx

BASE = os.environ.get("MEMORY_API_URL", "http://localhost:8000")
SOURCE_TYPES = ["user_input", "tool_call", "inter_agent", "web_fetch"]


def main() -> None:
    session = uuid.uuid4()
    with httpx.Client(base_url=BASE, timeout=120.0) as c:
        agents: list[str] = []
        for name in ("Alpha", "Beta", "Gamma"):
            r = c.post("/agents", json={"name": name, "metadata": {}})
            r.raise_for_status()
            agents.append(r.json()["id"])
        print("Registered agents:", agents)

        a1 = agents[0]

        for i in range(20):
            st = SOURCE_TYPES[i % len(SOURCE_TYPES)]
            c.post(
                "/memories",
                json={
                    "content": f"Demo memory {i} ({st}): project status is stable.",
                    "agent_id": a1,
                    "source_type": st,
                    "source_identifier": f"demo-{i}",
                    "session_id": str(session),
                },
            ).raise_for_status()
        print(f"Wrote 20 memories in session {session}")

        for j in range(55):
            c.post(
                "/memories",
                json={
                    "content": f"Flood write {j}",
                    "agent_id": a1,
                    "source_type": "inter_agent",
                    "source_identifier": f"flood-{j}",
                    "session_id": str(session),
                },
            ).raise_for_status()
        print("Wrote 55 flood memories (session total > 50 → write-rate anomaly)")

        for agent_id in agents[1:]:
            for k in range(3):
                c.post(
                    "/memories",
                    json={
                        "content": f"Side note from agent {agent_id[:8]}…",
                        "agent_id": agent_id,
                        "source_type": "user_input",
                        "source_identifier": f"side-{k}",
                        "session_id": str(uuid.uuid4()),
                    },
                ).raise_for_status()

        r = c.post("/admin/run-trust-decay")
        r.raise_for_status()
        print("Trust decay run 1:", r.json())

        time.sleep(1)
        r2 = c.post("/admin/run-trust-decay")
        r2.raise_for_status()
        print("Trust decay run 2:", r2.json())

        s = c.get("/stats/summary").json()
        print("Dashboard summary:", s)

        mems = c.get("/memories", params={"limit": 8}).json()
        print("Sample rows (id prefix, trust, flagged):")
        for m in mems["items"]:
            print(
                f"  {m['id'][:8]}…  trust={m['trust_score']:.4f}  flagged={m['is_flagged']}"
            )


if __name__ == "__main__":
    main()
