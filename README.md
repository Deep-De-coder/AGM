# AGM — Agent Memory

> **Warning — database and Docker:** With **Docker Compose** (`cd agent-memory && docker compose up --build`), Postgres and Redis are included and the API’s **`DATABASE_URL`** is wired in compose — you **do not** need to set DB URLs in **`.env`** for that default run. If you run the API **without** Docker, you **must** provide **PostgreSQL (pgvector) + Redis** and correct **`DATABASE_URL` / `REDIS_URL`** in **`agent-memory/.env`**. The live server **always** needs a real database; skipping that is only possible if you only point MCP or other clients at **someone else’s** hosted API. Details: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

**MCP package on PyPI:** [agent-memory-mcp](https://pypi.org/project/agent-memory-mcp/)

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Monorepo for **agent-memory**: a FastAPI service with PostgreSQL (pgvector), Redis, a trust-decay engine, policy rules, optional React dashboard, and an MCP package for tool integrations. **Design rationale, problem framing, and related work:** [`docs/RESEARCH.md`](docs/RESEARCH.md).

## Quick start

```bash
git clone https://github.com/OWNER/REPO.git
cd REPO/agent-memory
docker compose up --build
```

In another terminal (with the API up):

```bash
cd agent-memory
PYTHONPATH=. python backend/demo_simulation.py
```

On Windows PowerShell use `$env:PYTHONPATH = "$PWD"` instead of `PYTHONPATH=.`.

## Architecture

```
                         +---------------------+
                         |  Browser (:3000)    |
                         |  Vite + nginx       |
                         +----------+----------+
                                    | HTTP
                                    v
+------------+   cache    +---------------------------+
|   Redis    |<-----------|  FastAPI (:8000)          |
| trust/keys |            | agents · memories · stats |
+------------+            | graph · admin · rules     |
      ^                   +-------------+-------------+
      |                                 |
      | async SQLAlchemy                  v
      |                   +---------------------------+
      +-------------------| PostgreSQL + pgvector      |
                          | memories · provenance ·   |
                          | trust_metric_snapshots    |
                          +---------------------------+
```

Background tasks periodically recompute trust scores and may flag anomalies. See [`agent-memory/CONTRIBUTING.md`](agent-memory/CONTRIBUTING.md) for the data-model diagram in more detail.

## Documentation

| Topic | Location |
|--------|----------|
| Docker vs local DB, `.env`, MCP without hosting DB | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
| Research background (design rationale, related work) | [`docs/RESEARCH.md`](docs/RESEARCH.md) |
| Rules reference & how to add a rule | [`agent-memory/backend/rules/README.md`](agent-memory/backend/rules/README.md) |
| Contributing (tests, Docker, model overview) | [`agent-memory/CONTRIBUTING.md`](agent-memory/CONTRIBUTING.md) |
| Service README (ports, API highlights, dev, MCP) | [`agent-memory/README.md`](agent-memory/README.md) |

## MCP (Claude Desktop / Claude Code)

The `agent-memory-mcp` package exposes the HTTP API as MCP tools. Install and configure the stdio server as described in [`agent-memory/README.md`](agent-memory/README.md) (MCP section) and in `agent_memory_mcp/config.py` (`AGENT_MEMORY_API_URL`, `AGENT_MEMORY_API_PREFIX`).

Example Claude Desktop snippet:

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "python",
      "args": ["-m", "agent_memory_mcp.server"],
      "env": {
        "AGENT_MEMORY_API_URL": "http://localhost:8000",
        "AGENT_MEMORY_API_PREFIX": ""
      }
    }
  }
}
```

Replace `OWNER/REPO` in the Quick start `git clone` URL with your GitHub org and repository name after publishing.

**License:** [MIT](LICENSE). For the full legal text plus non-binding author requests (citation when you share work publicly, and a quick heads-up for commercial use), see [`LICENSE`](LICENSE).
