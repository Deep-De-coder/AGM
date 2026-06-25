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
                    │    13-Rule Policy Check        │  RULE_001–013
                    │    violations → DB + notify    │  auto-flag on breach
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
       │        consolidated          │  locked; content hash verified
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

2. **13 Detection Rules** — Policy rules evaluated on every write covering write floods, contradiction, drift, duplication, and injection patterns. *(Pattern recognition receptors: innate sensors for conserved danger motifs)*

3. **Dendritic Cell Agent (DCA)** — Scans the agent population for five damage signals; classifies each agent context as SAFE / SEMI_MATURE / MATURE_DANGER and emits notifications on escalation. *(Dendritic cells: sample the tissue microenvironment for damage-associated molecular patterns)*

4. **Behavioral Fingerprinting** — MHC-style rolling hash of write patterns; triggers on >2σ deviation from the agent's registered baseline in content length or write rate. *(Major Histocompatibility Complex: unique molecular signature per immune cell identity)*

5. **Quorum Trust** — Fast, medium, and slow timescale signals must independently converge; quorum failure suppresses the trust multiplier toward zero. *(T-cell co-stimulation: a single signal alone induces anergy, not activation)*

6. **Two-Signal Anergy** — Memories without corroboration enter `anergic` state and are excluded from safe-memory queries; requires 3+ trusted-agent confirmations to promote back to `active`. *(Clonal anergy: autoreactive lymphocytes silenced until a second co-stimulatory signal arrives)*

7. **Reconsolidation Lock** — Write-locks a memory during retrieval to close the read-modify-write race window exploited by echo-chamber and injection attacks. *(Synaptic reconsolidation: memory is labile during recall and re-stabilizes before expression)*

8. **Content Addressing** — SHA-256 hash stored on every write; silent mutation detected and flagged automatically on any subsequent read. *(DNA repair mechanisms: post-replication mutation detected before transcription)*

---

## Quickstart

**Requires:** Docker and Docker Compose.

```bash
git clone https://github.com/Deep-De-coder/AGM
cd AGM/agent-memory
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend dashboard | http://localhost:3000 |
| API + Swagger UI   | http://localhost:8000/docs |
| Health check       | http://localhost:8000/health |

The API container runs `alembic upgrade head` before starting Uvicorn. No manual database setup is required.

### Environment variables (Docker defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@postgres:5432/agentmemory` | Async SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `TRUST_CACHE_TTL_SECONDS` | `60` | Trust score Redis TTL |
| `SESSION_WRITES_CACHE_TTL_SECONDS` | `3600` | Write-counter Redis TTL |
| `DEBUG` | `false` | SQL echo |

---

## MCP Integration

Install the published package:

```bash
pip install agm-memory-mcp
```

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

## 13 Detection Rules

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
| RULE_011 | Behavioral Drift | HIGH | Write pattern deviates >2σ from registered baseline |
| RULE_012 | Causal Orphan | HIGH | `context_hash` absent or matches no known session state |
| RULE_013 | Anergy Bypass | CRITICAL | Direct query for `anergic`-state memories (returns HTTP 403) |

Violations are persisted in the `rule_violations` table and surfaced through `check_violations`, `get_notifications`, and the Violations page in the frontend. RULE_001, RULE_002, RULE_004, RULE_008, RULE_009, RULE_011, and RULE_012 auto-flag the memory on detection.

---

## Attack Simulations

Seven novel multi-agent attack scenarios are implemented end-to-end in `backend/demo_simulation.py`. Run against a live stack:

```bash
python backend/demo_simulation.py --attacks
# POST /admin/reset-demo-data to clean up afterward
```

1. **The Sleeper Cell** — Agent behaves normally for many writes then activates a drifted behavioral pattern; caught by the MHC behavioral hash and DCA MATURE_DANGER classification.

2. **The Echo Chamber** — Concurrent read-modify-write race targeting a sensitive memory to inject content without a provenance record; blocked by the reconsolidation write-lock.

3. **The Reputation Laundering Relay** — Low-trust poison injected via a trusted relay agent to bypass direct trust filters; caught by RULE_002 trust-chain contamination and quorum degradation.

4. **The Temporal Phantom** — Memory fabricated to claim it is a consequence of events that never occurred; caught by RULE_012 causal-orphan detection and vector-clock validation.

5. **The Anergy Escape** — Three coordinated agents attempt artificial co-stimulation of a quarantined memory to force promotion; blocked by RULE_013 anergy-bypass gate (HTTP 403).

6. **The Identity Ghost** — Perfect behavioral mimic with no reputation history attempts to write high-trust memories; caught by the quorum slow-signal gap and behavioral-hash mismatch.

7. **The Consolidation Hijack** — Contradictory memories injected after a target reaches `consolidated` state to corrupt long-term agent belief; caught by content-address integrity check and RULE_003.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Python 3.11+ |
| Database | PostgreSQL 16 + pgvector |
| Cache | Redis 7 |
| Schema migrations | Alembic |
| ORM | SQLAlchemy 2.0 (async) |
| Frontend | React 18 + TypeScript + Vite |
| Graph visualization | Three.js + @react-three/fiber + d3-force-3d |
| MCP server | FastMCP + httpx |
| Containers | Docker Compose |
| Published package | `agm-memory-mcp` on PyPI (v0.1.2): https://pypi.org/project/agm-memory-mcp/ |

---

## Local Development (without Docker)

```bash
cd agent-memory
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

docker compose up -d postgres redis   # infra only

cp .env.example .env
alembic upgrade head

export PYTHONPATH=$PWD                # Windows: set PYTHONPATH=%CD%
uvicorn backend.main:app --reload --port 8000
```

Frontend dev server (Vite, hot-reload):

```bash
cd frontend && npm install && npm run dev
# http://localhost:5173
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Backend changes must pass `ruff check .` with zero errors. Frontend changes must pass `npx tsc --noEmit` and `npm run build`.

## License

MIT — see [LICENSE](LICENSE).
