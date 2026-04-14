# agent-memory

Production-grade **provenance-tagged agent memory** service: **FastAPI** + **PostgreSQL** (with **pgvector**) + **Redis**. Every memory write, read, trust change, and soft delete is recorded in `memory_provenance_log`.

> **Docker vs `.env`:** `docker compose up --build` sets **`DATABASE_URL`** / **`REDIS_URL`** for the `api` container in `docker-compose.yml` — no DB entries in **`.env`** are required for that path. Running **uvicorn locally** requires your own Postgres + Redis and a populated **`.env`**. Monorepo overview: [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

## Architecture

- **PostgreSQL** stores agents, memories (including optional `VECTOR(1536)` embeddings), and the full audit trail.
- **Redis** caches per-memory trust scores (`trust:{memory_id}`, TTL 60s) and per-session write counters for anomaly detection (`writes:{agent_id}:{session_id}`, TTL 3600s).
- **Alembic** owns schema changes; the API does not auto-create tables in production.

### Repository layout

```
agent-memory/
  backend/
    main.py
    models.py
    database.py
    redis_client.py
    routers/
      memories.py
      agents.py
      trust.py
    schemas.py
    config.py
  alembic/
  docker-compose.yml
  requirements.txt
  .env.example
  README.md
```

Provenance helpers live in `database.py` (`log_memory_event`) to avoid import cycles. The optional `agent_memory_mcp/` package (see below) wraps the same HTTP API.

### Schema note: soft delete

`memories.is_deleted` is set on `DELETE /memories/{id}`; the row is retained and `GET /memories/{id}/provenance` remains available for audit.

## Prerequisites

- Python 3.12+ (3.10+ should work)
- Docker and Docker Compose (recommended), or local PostgreSQL 16+ with pgvector and Redis 7+

## Quick start (Docker)

From the `agent-memory` directory:

```bash
docker compose up --build
```

The API listens on **http://localhost:8000**. The image runs `alembic upgrade head` before starting Uvicorn.

- OpenAPI docs: http://localhost:8000/docs  
- Health: `GET /health`

## Local development (without Docker)

1. **Create a virtual environment and install dependencies**

   ```bash
   cd agent-memory
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Start PostgreSQL and Redis** (or use Docker only for infra):

   ```bash
   docker compose up -d postgres redis
   ```

3. **Configure environment**

   ```bash
   copy .env.example .env
   ```

   Adjust `DATABASE_URL` and `REDIS_URL` if needed.

4. **Run migrations**

   ```bash
   alembic upgrade head
   ```

5. **Run the API** (from `agent-memory`, with `backend` importable):

   ```bash
   set PYTHONPATH=%CD%
   uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```

   On Linux or macOS: `export PYTHONPATH=$PWD`

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/agent_memory` | Async SQLAlchemy URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `APP_NAME` | `agent-memory` | FastAPI title |
| `DEBUG` | `false` | SQL echo when `true` |
| `TRUST_CACHE_TTL_SECONDS` | `60` | Redis TTL for `trust:*` keys |
| `SESSION_WRITES_CACHE_TTL_SECONDS` | `3600` | Redis TTL for `writes:*` keys |

## Database migrations

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1
```

Initial revision `001_initial` enables the `vector` extension and creates `agents`, `memories`, and `memory_provenance_log`.

## API examples (`curl`)

Set a base URL and create variables for IDs returned by the API:

```bash
set BASE=http://localhost:8000
```

### `POST /agents` — register an agent

```bash
curl -s -X POST "%BASE%/agents" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\": \"research-agent-1\", \"metadata\": {\"team\": \"nlp\"}}"
```

Response includes `id` (use as `AGENT_ID` below).

### `GET /agents/{agent_id}` — get agent

```bash
curl -s "%BASE%/agents/AGENT_ID"
```

### `POST /memories` — write a memory

```bash
curl -s -X POST "%BASE%/memories" ^
  -H "Content-Type: application/json" ^
  -d "{\"content\": \"User prefers metric units.\", \"agent_id\": \"AGENT_ID\", \"source_type\": \"user_input\", \"source_identifier\": \"chat-turn-7\", \"safety_context\": {\"model\": \"gpt-4.1\", \"human_verified\": false}, \"session_id\": \"550e8400-e29b-41d4-a716-446655440000\"}"
```

Returns `memory_id` and `trust_score` (initially `1.0`). A provenance row with `event_type=write` is inserted.

### `GET /memories/{memory_id}` — get memory and provenance snapshot

```bash
curl -s "%BASE%/memories/MEMORY_ID"
```

Optional query: `reader_agent_id` to attribute the read in the audit log.

```bash
curl -s "%BASE%/memories/MEMORY_ID?reader_agent_id=AGENT_ID"
```

### `GET /memories` — list / filter

```bash
curl -s "%BASE%/memories"
curl -s "%BASE%/memories?agent_id=AGENT_ID&source_type=user_input&min_trust_score=0.5&flagged_only=false&limit=20&offset=0"
```

### `GET /memories/{memory_id}/provenance` — audit trail only

```bash
curl -s "%BASE%/memories/MEMORY_ID/provenance"
```

Works for any existing memory row (including soft-deleted), so you can still retrieve the audit trail after deletion.

### `GET /memories/{memory_id}/trust` — current trust snapshot

```bash
curl -s "%BASE%/memories/MEMORY_ID/trust"
```

### `POST /memories/{memory_id}/flag` — flag a memory (anomaly / review)

```bash
curl -s -X POST "%BASE%/memories/MEMORY_ID/flag" ^
  -H "Content-Type: application/json" ^
  -d "{\"reason\": \"possible hallucination\", \"performed_by_agent_id\": \"AGENT_ID\"}"
```

### `DELETE /memories/{memory_id}` — soft delete

```bash
curl -s -o NUL -w "%%{http_code}" -X DELETE "%BASE%/memories/MEMORY_ID"
```

Optional: `performed_by_agent_id` query parameter. The row stays in the database; `is_deleted` is set and a `deleted` event is logged.

### `PATCH /memories/{memory_id}/trust` — update trust (optional helper)

```bash
curl -s -X PATCH "%BASE%/memories/MEMORY_ID/trust" ^
  -H "Content-Type: application/json" ^
  -d "{\"trust_score\": 0.85, \"performed_by_agent_id\": \"AGENT_ID\", \"reason\": \"validated externally\"}"
```

### `GET /health`

```bash
curl -s "%BASE%/health"
```

---

## MCP package (`agent-memory-mcp`)

This repo ships a **Model Context Protocol** server (`agent_memory_mcp`) that wraps the same HTTP API as `curl` above. Install it as a standalone package (name **`agent-memory-mcp`**, import **`agent_memory_mcp`):

```bash
pip install .
```

### Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `AGENT_MEMORY_API_URL` | `http://localhost:8000` | FastAPI base URL (no trailing slash). |
| `AGENT_MEMORY_API_PREFIX` | *(empty)* | Only set if you mount routes under a prefix; default matches this project (`/agents`, `/memories` at server root). |

### 1. Run the MCP server (stdio)

The HTTP API must be running first. Then start the MCP process (normally launched by an MCP host; stdio is used for JSON-RPC on stdin/stdout):

```bash
python -m agent_memory_mcp.server
```

With a non-default API URL:

```bash
set AGENT_MEMORY_API_URL=http://127.0.0.1:9000
python -m agent_memory_mcp.server
```

On Linux or macOS, use `export` instead of `set`.

### 2. Claude Desktop / Claude Code configuration

Add a server entry (adjust the `python` path if needed). Example for **Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "python",
      "args": ["-m", "agent_memory_mcp.server"],
      "env": {
        "AGENT_MEMORY_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

**Claude Code** uses the same `mcpServers` shape in its MCP settings. Restart the app after editing.

### 3. LangGraph with the MCP adapter

Install:

```bash
pip install langchain-mcp-adapters langgraph
```

Example: load MCP tools via stdio and build a LangGraph agent:

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain.chat_models import init_chat_model


async def main():
    client = MultiServerMCPClient(
        {
            "agent_memory": {
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "agent_memory_mcp.server"],
                "env": {"AGENT_MEMORY_API_URL": "http://localhost:8000"},
            }
        }
    )
    tools = await client.get_tools()
    model = init_chat_model("openai:gpt-4.1-mini")
    agent = create_react_agent(model, tools)
    result = await agent.ainvoke(
        {"messages": [("user", "Use query_memories with min_trust_score 0.5.")]}
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

Use `async with client.session("agent_memory") as session:` and `load_mcp_tools` when you need one long-lived MCP subprocess (see [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)).

### 4. Safe reasoning before retrieval

Before using memory content in high-stakes or multi-step reasoning, call **`get_safe_memories`** (or **`query_memories`** with a strict `min_trust_score`) so you only surface memories that meet trust, flag, and violation filters. Example pattern:

```python
safe = await tools["get_safe_memories"].ainvoke(
    {"min_trust_score": 0.7, "exclude_flagged": True, "limit": 15}
)
# Use only items from `safe` as context; optionally cross-check `check_violations` per id.
```

### 5. Monitoring loop: notifications

For long-running agents, poll **`get_notifications`** every *N* steps (or on a timer) so security and trust alerts are not missed:

```python
N = 20
for step in range(1000):
    # ... main agent work ...
    if step % N == 0:
        notes = await tools["get_notifications"].ainvoke({})
        for n in notes:
            if not n.get("read"):
                # surface or log n["title"], n["message"], n["severity"]
                pass
```

### 6. Inter-agent memory warning

Memories with **`source_type="inter_agent"`** can carry higher provenance risk. Always call **`check_violations`** (or **`run_rules_check`**) before acting on them in critical reasoning, and treat **`RULE_006`** (inter-agent without session) as a signal to review provenance.

### 7. Three-agent workflow (conceptual)

**Agent A** registers and writes a memory. **Agent B** reads it and writes a follow-up. **Agent C** queries with a trust threshold. The same sequence applies if a single LLM orchestrates tool calls.

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient


async def three_agent_workflow():
    mcp = MultiServerMCPClient(
        {
            "mem": {
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "agent_memory_mcp.server"],
                "env": {"AGENT_MEMORY_API_URL": "http://localhost:8000"},
            }
        }
    )
    tools = {t.name: t for t in await mcp.get_tools()}

    reg_a = await tools["register_agent"].ainvoke(
        {"name": "Researcher A", "metadata": {"role": "writer"}}
    )
    # Tool outputs may be JSON strings — parse in your stack as needed.
    agent_a_id = reg_a["agent_id"] if isinstance(reg_a, dict) else reg_a

    write_a = await tools["write_memory"].ainvoke(
        {
            "content": "Baseline: project codename is AGM.",
            "agent_id": agent_a_id,
            "source_type": "user_prompt",
            "source_identifier": "session-001",
            "safety_context": {"classification": "internal"},
        }
    )
    memory_id = write_a["memory_id"] if isinstance(write_a, dict) else write_a

    reg_b = await tools["register_agent"].ainvoke({"name": "Analyst B", "metadata": {"role": "reader"}})
    agent_b_id = reg_b["agent_id"] if isinstance(reg_b, dict) else reg_b

    await tools["read_memory"].ainvoke({"memory_id": memory_id})
    await tools["write_memory"].ainvoke(
        {
            "content": "Follow-up: codename AGM confirmed by Analyst B.",
            "agent_id": agent_b_id,
            "source_type": "derivation",
            "source_identifier": "session-001/b",
            "safety_context": {},
        }
    )

    out = await tools["query_memories"].ainvoke({"min_trust_score": 0.5, "limit": 10})
    memories = out["memories"] if isinstance(out, dict) else out
    return memories


# asyncio.run(three_agent_workflow())
```

### MCP tools

| Tool | Role |
|------|------|
| `write_memory` | Create memory with provenance (`session_id`, `safety_context` optional). |
| `read_memory` | Fetch one memory; API logs read in provenance when configured. |
| `query_memories` | Returns `{"memories": [...]}` with filters. |
| `get_trust_score` | Trust and flag fields for one memory (`GET /memories/{id}/trust`). |
| `get_provenance` | Returns `{"events": [...]}` audit trail. |
| `flag_memory` | Manual flag with reason. |
| `register_agent` | Returns `agent_id` and `name`. |
| `check_violations` | List rule hits for a memory (`GET /violations?memory_id=...`). |
| `get_safe_memories` | Memories above trust threshold, not flagged, no unacknowledged violations (`GET /memories/safe`). |
| `acknowledge_violation` | Acknowledge a violation after review (`POST /violations/{id}/acknowledge`). |
| `get_notifications` | Recent security/trust notifications (`GET /notifications`). |
| `run_rules_check` | Run rules on a memory and return findings (`POST /memories/{id}/check-rules`). |
| `get_rules_reference` | Static list of all 10 predefined rules (no HTTP call). |

**HTTP mapping:** the MCP client calls the FastAPI routes under `/memories`, `/agents`, `/violations`, and `/notifications` (trust is exposed at `/memories/{id}/trust`). When the API returns HTTP status ≥ 400, tools raise an MCP error whose message is the backend error body (for example FastAPI `detail`).

### Errors if the backend is down

Tool calls surface a clear error explaining that the AgentMemory API was unreachable, with hints to start Uvicorn and verify `AGENT_MEMORY_API_URL`.
