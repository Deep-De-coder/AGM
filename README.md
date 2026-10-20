# AGM — Agent Memory

> **Database:** `docker compose up` includes PostgreSQL (pgvector) and Redis and wires them up for you — no `.env` needed. Running the API *without* Docker means bringing your own PostgreSQL + pgvector and Redis; see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

**MCP package on PyPI:** [agm-memory-mcp](https://pypi.org/project/agm-memory-mcp/)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Monorepo for **agent-memory**: a FastAPI service with PostgreSQL (pgvector), Redis, a trust-decay engine, policy rules, optional React dashboard, and an MCP package for tool integrations. **Design rationale, problem framing, and related work:** [`docs/RESEARCH.md`](docs/RESEARCH.md).

## Quick start

**Requires:** [Docker](https://docs.docker.com/get-docker/) with Compose v2 (Docker Desktop on macOS/Windows, or Docker Engine + compose plugin on Linux). Nothing else — no Python or Node needed on the host.

```bash
git clone https://github.com/Deep-De-coder/AGM.git
cd AGM/agent-memory
docker compose up --build
```

First build takes a few minutes. When the logs show `Uvicorn running`, open:

| | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |

Populate it with demo agents, rule violations and the 7 attack simulations (second terminal, same folder):

```bash
docker compose exec api python backend/demo_simulation.py
```

On macOS/Linux/WSL, `./run.sh` does both steps in one command. Ports busy? See [Troubleshooting](agent-memory/README.md#troubleshooting).

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

The [`agm-memory-mcp`](https://pypi.org/project/agm-memory-mcp/) package exposes the HTTP API as MCP tools. With the stack running:

```bash
pip install agm-memory-mcp
agm-memory-mcp --check --api-url http://localhost:8000
```

Claude Desktop / Claude Code config:

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

Full tool list and options: [`agent-memory/README.md`](agent-memory/README.md#mcp-integration).

**License:** [MIT](LICENSE). For the full legal text plus non-binding author requests (citation when you share work publicly, and a quick heads-up for commercial use), see [`LICENSE`](LICENSE).
