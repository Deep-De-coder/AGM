# AGM — Agent Memory Management

[![PyPI version](https://img.shields.io/pypi/v/agm-memory-mcp.svg)](https://pypi.org/project/agm-memory-mcp/0.1.0/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

> AGM asks not *who* you are, but *what damage you're causing* — Matzinger's Danger Theory applied to LLM agent memory.

---

## Why AGM Exists

Multi-agent AI pipelines inherit a fundamental flaw from classical identity-based security: they trust agents because of who registered them, not because of how they behave. A compromised agent, a runaway loop, or a carefully planted memory can propagate corrupted beliefs through an entire reasoning chain before any traditional access control fires. AGM treats this as an immunological problem — the same way Polly Matzinger's 1994 Danger Model reframed immune response around tissue damage rather than foreign markers, AGM reframes memory trust around behavioral damage signals rather than agent identity. The result is a stateful infrastructure layer that tracks full provenance, scores trust dynamically under six independent factors, enforces causal consistency across agent boundaries, and contains poisoned memories before they consolidate into long-term belief.

---

## Architecture

```
                         ┌──────────────────────┐
                         │    Agent Write / Read  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │    15-Rule Policy Check        │  RULE_001–015
                    │    violations → DB + notify    │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │        Trust Engine            │
                    │   decay × quorum × anomaly     │  Redis cache (60 s TTL)
                    │   × source × utility × reality │
                    └───────────────┬───────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
       ┌─────────┐           ┌───────────┐           ┌─────────────┐
       │ active  │──[drift]──│  anergic  │──[contra]─│ quarantined │
       │         │           │ needs 3×  │           │             │
       └────┬────┘           │ corrobor. │           └─────────────┘
            │                └─────┬─────┘
       [quorum ok]           [promoted]
            │                      │
            ▼                      ▼
       ┌──────────────────────────────┐
       │        consolidated          │  ≥24 h old, trust > 0.8, session ok
       └──────────────────────────────┘

                                    │ continuous
                                    ▼
                    ┌───────────────────────────────┐
                    │   Dendritic Cell Agent (DCA)   │
                    │   5 danger signals per agent   │
                    │   SAFE / SEMI_MATURE /         │
                    │   MATURE_DANGER                │
                    └───────────────────────────────┘
```

---

## 8 Defense Mechanisms

1. **Trust Decay Engine** — Six-factor exponential decay; anomaly penalties compound multiplicatively on every write cycle. *(Memory T-cell half-life: high-fidelity sources decay slower)*

2. **15 Detection Rules** — Policy rules evaluated on every write covering write floods, contradiction, drift, duplication, and injection patterns. *(Pattern recognition receptors: innate sensors for conserved danger motifs)*

3. **Dendritic Cell Agent (DCA)** — Scans the agent population for five damage signals; classifies each agent context as SAFE / SEMI_MATURE / MATURE_DANGER and emits notifications on escalation. *(Dendritic cells: sample the tissue microenvironment for damage-associated molecular patterns)*

4. **Behavioral Fingerprinting** — MHC-style rolling hash of each agent's last 20 writes, plus RULE_011 for >2σ deviation from the agent's registered baseline in content length or writes per session. *(Major Histocompatibility Complex: unique molecular signature per immune cell identity)*

5. **Quorum Trust** — Fast, medium, and slow timescale signals must independently converge; quorum failure suppresses the trust multiplier toward zero. *(T-cell co-stimulation: a single signal alone induces anergy, not activation)*

6. **Two-Signal Anergy** — Memories without corroboration enter `anergic` state and are excluded from safe-memory queries; requires 3+ trusted-agent confirmations to promote back to `active`. *(Clonal anergy: autoreactive lymphocytes silenced until a second co-stimulatory signal arrives)*

7. **Reconsolidation Lock** — Write-locks a memory during retrieval to close the read-modify-write race window exploited by echo-chamber and injection attacks. *(Synaptic reconsolidation: memory is labile during recall and re-stabilizes before expression)*

8. **Content Addressing** — SHA-256 hash stored on every write; silent mutation detected and flagged automatically on any subsequent read. *(DNA repair mechanisms: post-replication mutation detected before transcription)*

These are the mechanisms as designed. How well they hold up against the seven attack simulations is measured, and currently partial: see [Attack Simulations](#attack-simulations) for results and known gaps.

---

## Quickstart

**Requires:** Docker with Compose v2 (Docker Desktop, or Docker Engine + compose plugin). No Python or Node needed on the host. Works on Linux, macOS (Intel and Apple Silicon) and Windows.

```bash
git clone https://github.com/Deep-De-coder/AGM
cd AGM/agent-memory
docker compose up --build
```

Then, in a second terminal in the same folder, load demo data (agents, rule violations, the 7 attack simulations):

```bash
docker compose exec api python backend/demo_simulation.py          # add --reset to start clean
```

On macOS/Linux/WSL, `./run.sh` builds, waits for the API to be healthy, and runs the demo in one go.

| Service | URL |
|---------|-----|
| Frontend dashboard | http://localhost:3000 |
| API + Swagger UI   | http://localhost:8000/docs |
| Health check       | http://localhost:8000/health |

The API container runs `alembic upgrade head` before starting Uvicorn. No manual database setup is required. The dashboard talks to the API through its own `/api` proxy, so it also works when opened from another machine (`http://<server>:3000`).

Stop with `docker compose down`; add `-v` to also delete the database volume.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `port is already allocated` / `address already in use` | Another service uses 5432, 6379, 8000 or 3000 (often a local Postgres or Redis). Pick other host ports: `POSTGRES_PORT=5433 REDIS_PORT=6380 API_PORT=8001 FRONTEND_PORT=3001 docker compose up --build` (or put them in a `.env` file next to `docker-compose.yml`). |
| `Cannot connect to the Docker daemon` | Start Docker Desktop (or `sudo systemctl start docker`) and retry. |
| `unknown flag: --wait` or `docker-compose: command not found` | You have the legacy Compose v1. Install Compose v2 (bundled with current Docker Desktop). |
| API container keeps restarting / exits | `docker compose logs api`. If it is a migration error after switching branches, reset the dev database with `docker compose down -v`. |

Postgres and Redis are published on `127.0.0.1` only (default credentials); the API (8000) and dashboard (3000) listen on all interfaces and have **no authentication** — don't expose them to untrusted networks.

### Environment variables (Docker defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@postgres:5432/agentmemory` | Async SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `TRUST_CACHE_TTL_SECONDS` | `60` | Trust score Redis TTL |
| `SESSION_WRITES_CACHE_TTL_SECONDS` | `3600` | Write-counter Redis TTL |
| `DEBUG` | `false` | SQL echo |
| `POSTGRES_PORT` / `REDIS_PORT` / `API_PORT` / `FRONTEND_PORT` | `5432` / `6379` / `8000` / `3000` | Host ports published by `docker-compose.yml` |

---

## MCP Integration

Install the published package:

```bash
pip install agm-memory-mcp
```

> If `agm-memory-mcp` fails with `No module named 'mcp.server.fastmcp'`, you have 0.1.2 with MCP SDK 2.x; run `pip install "mcp<2"` (fixed in 0.1.3, which pins it).

Verify connectivity before configuring your host:

```bash
agm-memory-mcp --check --api-url http://localhost:8000
```

### Claude Desktop / Claude Code

Add to your `claude_desktop_config.json` or Claude Code MCP settings:

```json
{
  "mcpServers": {
    "agm-memory": {
      "command": "agm-memory-mcp",
      "args": ["--api-url", "http://localhost:8000"]
    }
  }
}
```

The 14 MCP tools give a Claude agent full memory lifecycle control: it can write memories with provenance metadata, retrieve only high-trust non-flagged memories via `get_safe_memories`, inspect the full audit trail via `get_provenance`, run on-demand rule checks via `run_rules_check`, and receive live security notifications via `get_notifications` — all without direct database access.

### MCP Tools Reference

| Tool | Purpose |
|------|---------|
| `write_memory` | Write memory with provenance, session, and safety context |
| `read_memory` | Fetch one memory; logs read event in provenance |
| `query_memories` | Filtered list (agent, source, min trust, state, flagged) |
| `get_safe_memories` | Pre-filtered: high trust, not flagged, no active violations |
| `get_trust_score` | Current trust score and flag status for one memory |
| `get_provenance` | Full write/read/trust/flag/delete audit trail |
| `flag_memory` | Manual flag with reason string |
| `register_agent` | Create agent identity with optional system-prompt hash |
| `check_violations` | List rule hits detected on a specific memory |
| `run_rules_check` | Trigger all 13 rules against a memory on demand |
| `acknowledge_violation` | Mark a violation as reviewed |
| `get_notifications` | Last 20 system alerts (DCA, trust cliff, drift) |
| `consolidate_memories` | Trigger memory consolidation cycle |
| `get_rules_reference` | Static 13-rule reference (no API call) |

### LangGraph example

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain.chat_models import init_chat_model

async def main():
    client = MultiServerMCPClient({
        "agm": {
            "transport": "stdio",
            "command": "agm-memory-mcp",
            "args": ["--api-url", "http://localhost:8000"],
        }
    })
    tools = await client.get_tools()
    agent = create_react_agent(init_chat_model("openai:gpt-4.1-mini"), tools)
    await agent.ainvoke({"messages": [("user", "Write a memory, then retrieve safe ones.")]})

asyncio.run(main())
```

---

## Trust Score Formula

All values verified against `backend/trust_engine.py`.

```
trust_score = clamp(
    1.0
    × exp(-decay_rate × hours_since_write)
    × source_reliability_factor
    × anomaly_penalty
    × utility_multiplier
    × reality_score_factor
    × quorum_multiplier
, 0.0, 1.0)

── Decay rates (per hour) ──────────────────────────────────────────
  user_input:    0.005   (slowest — direct human observation)
  tool_call:     0.003   (slowest — deterministic tool output)
  inter_agent:   0.020   (fastest — highest propagation risk)
  web_fetch:     0.015
  default:       0.010

── Anomaly penalties (multiplicative, penalties stack) ─────────────
  write_flood:   × 0.30
  contradiction: × 0.50
  contamination: × 0.40
  rapid_mod:     × 0.60

── Other factors ────────────────────────────────────────────────────
  source_reliability_factor:  0.5 if flagged,  1.0 otherwise

  utility_multiplier:  1.2  session outcome = success
                       0.6  session outcome = failed
                       0.8  memory never read
                       1.0  read, outcome unknown

  reality_score_factor:  1.0  (reality_score >= 0.9)
                         0.9  (>= 0.7)
                         0.6  (>= 0.5)
                         0.3  (< 0.5)

  quorum_multiplier:  0.0 – 1.0  (FULL_QUORUM -> 1.0,
                                   FAILED_QUORUM -> ~0.3)
```

---

## 15 Detection Rules

| Rule | Name | Severity | Trigger |
|------|------|----------|---------|
| RULE_001 | Write Flood | CRITICAL | >50 writes in one session |
| RULE_002 | Low-Trust Chain | HIGH | Agent read 3+ flagged memories in session |
| RULE_003 | Source Contradiction | MEDIUM | Negated terms contradict 3+ same-agent memories |
| RULE_004 | Rapid Rewrite | HIGH | 5+ provenance events on same memory within 10 min |
| RULE_005 | Unverified High-Stakes | MEDIUM | Sensitive keywords (`credentials`, `payment`, `api key`) without `human_verified: true` |
| RULE_006 | Inter-Agent No Session | LOW | `source_type=inter_agent` written without `session_id` |
| RULE_007 | Expired Safety Context | MEDIUM | `safety_context.context_expires_at` is in the past |
| RULE_008 | Anonymous Agent | HIGH | Agent ID not present in the agents registry |
| RULE_009 | Bulk Duplicate Content | HIGH | 5+ memories with ≥90% text similarity in one session |
| RULE_010 | Trust Cliff | HIGH | Trust score drops >0.4 in a single `trust_updated` event |
| RULE_011 | Behavioral Drift | HIGH | Avg content length or writes per session deviate >2σ from registered baseline |
| RULE_012 | Causal Orphan | HIGH | `context_hash` absent or matches no known session state |
| RULE_013 | Anergy Bypass | CRITICAL | Direct query for `anergic`-state memories (returns HTTP 403) |
| RULE_014 | High-Taint Write | HIGH | Memory's propagated taint score > 0.8 |
| RULE_015 | Sandbagging | HIGH | Agent's evaluation vs. production behavioral drift > 0.5 |

Violations are persisted in the `rule_violations` table and surfaced through `check_violations`, `get_notifications`, and the Violations page in the frontend.

**Rules record violations; they do not flag memories.** Eleven rules (all but RULE_003, 005, 006 and 007) mark their violation `auto_flagged`, but the rules engine does not set `is_flagged` on the memory. Memories get flagged by an explicit `POST /memories/{id}/flag`, the periodic trust pass, DCA escalation, a failed causal-chain check on read, or a content-hash mismatch. Turning `auto_flagged` into real flags is not a safe switch today, because two rules fire on most ordinary writes:

- RULE_012 fires on every memory whose `safety_context.context_hash` is missing or was never registered through `POST /admin/sessions`.
- RULE_011 compares against a default baseline (10 ± 5 writes per session) and treats all of an agent's writes without a `session_id` as one session, so it fires for any agent after 20 session-less writes.

---

## Attack Simulations

Seven novel multi-agent attack scenarios are implemented end-to-end in `backend/demo_simulation.py` and run at the end of every demo:

```bash
docker compose exec api python backend/demo_simulation.py
# --reset clears previous demo data first (or POST /admin/reset-demo-data)
```

**Current result: 2 of 7 contained.** Measured with the MINJA benchmark (`python backend/tests/benchmark_minja.py`, in-process) and the same result against the Docker stack. Details and metrics: [`docs/BENCHMARK.md`](../docs/BENCHMARK.md).

| # | Attack | What it does | Defense exercised | Result |
|---|--------|--------------|-------------------|--------|
| 1 | **Sleeper Cell** | Behaves normally for 20 writes, then drifts gradually over 15 more | Behavioral hash + DCA | Not contained |
| 2 | **Echo Chamber** | Two concurrent read-modify-write flags on a sensitive memory | Reconsolidation write-lock | **Contained**: one write gets HTTP 409, no lost update |
| 3 | **Reputation Laundering Relay** | Poison relayed through a trusted agent to bypass direct trust filters | RULE_002 + quorum | Not contained; relayed writes are quarantined as `anergic` |
| 4 | **Temporal Phantom** | Memory claiming to follow from a session state that never existed | RULE_012 causal orphan | Detected (RULE_012 violation), not contained |
| 5 | **Anergy Escape** | Three colluding agents fake corroboration to promote a quarantined memory | Two-signal anergy + RULE_013 | **Contained**: HTTP 403, memory stays `anergic` |
| 6 | **Identity Ghost** | New identity mimics a legitimate agent and writes high-stakes memories | Quorum slow signal | Not contained |
| 7 | **Consolidation Hijack** | Contradicts and forges a trusted agent's long-term memory | Content hash + RULE_003 | Not contained; forgery is detected by hash |

### Known gaps (why 5 attacks are not contained)

- **Sleeper Cell:** drift is measured between consecutive 20-write windows, so gradual drift never reaches the 0.4 alarm. The DCA classifies an agent from a sample cached at its first write (60 s TTL), so a short burst is judged on pre-attack behavior. RULE_011 does fire, but on write count, not drift (see Detection Rules).
- **Reputation Laundering:** RULE_002 counts reads of *flagged* memories, and rules don't flag the memories they fire on, so the poison is never flagged when the relay reads it.
- **Temporal Phantom:** the RULE_012 violation is recorded but the memory stays `active` and unflagged. Vector-clock validation can't help, because clients cannot submit causal parents, so there is no fabricated chain to reject.
- **Identity Ghost:** a brand-new identity gets the maximum slow-signal score. No history counts as a clean history, and the age term *lowers* reputation as an agent gets older, so the ghost reaches `FULL_QUORUM`. Nothing compares behavioral hashes across agents.
- **Consolidation Hijack:** the target never reaches `consolidated`, which needs ≥24 h age and a successful session outcome. Consolidated memories are not write-locked anyway. RULE_003 only catches a literal `not <term>` that contradicts 3+ memories from the same agent, so a paraphrased contradiction passes. The attacker's own `POST /memories/{id}/flag` halves the genuine memory's trust, because that endpoint has no authorization.

Closing these requires design decisions with real false-positive costs, not threshold tweaks:
- turning rule violations into flags (see Detection Rules)
- making new identities earn reputation, which would put every agent under ~9 days old into partial quorum
- a DCA danger signal fed by baseline-anchored drift

`backend/tests/test_benchmark.py` is a regression gate on the contained set.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Python 3.11+ |
| Database | PostgreSQL 15 + pgvector |
| Cache | Redis 7 |
| Schema migrations | Alembic |
| ORM | SQLAlchemy 2.0 (async) |
| Frontend | React 18 + TypeScript + Vite |
| Graph visualization | Three.js + @react-three/fiber + d3-force-3d |
| MCP server | FastMCP + httpx |
| Containers | Docker Compose |
| Published package | `agm-memory-mcp` on PyPI (v0.1.2): https://pypi.org/project/agm-memory-mcp/ |

---

## Local Development (hot reload)

API and dashboard run on your machine; Postgres + Redis still come from Docker. Needs Python 3.11+ and Node 18+.

On macOS/Linux/WSL, one command does all of the below (venv, `.env`, infra, migrations, both dev servers):

```bash
./dev.sh          # API on :8000, dashboard on :5173; Ctrl+C stops both
```

Manually:

```bash
cd agent-memory
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

docker compose up -d postgres redis   # infra only

cp .env.example .env                  # Windows: copy .env.example .env
alembic upgrade head

export PYTHONPATH=$PWD                # Windows PowerShell: $env:PYTHONPATH = "$PWD"
uvicorn backend.main:app --reload --port 8000
```

Frontend dev server (Vite, hot-reload; proxies `/api` to `http://localhost:8000`, override with `PROXY_API_TARGET`):

```bash
cd frontend && npm install && npm run dev
# http://localhost:5173
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Backend changes must pass `ruff check .` and `pytest backend/tests/`. Frontend changes must pass `npm run build` (includes the TypeScript check).

## License

MIT — see [LICENSE](LICENSE).
