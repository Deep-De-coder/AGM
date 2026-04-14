# AGM — Agent Memory

**MCP package on PyPI:** [agent-memory-mcp](https://pypi.org/project/agent-memory-mcp/)

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Monorepo for **agent-memory**: a FastAPI service with PostgreSQL (pgvector), Redis, a trust-decay engine, policy rules, optional React dashboard, and an MCP package for tool integrations.

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
| Rules reference & how to add a rule | [`agent-memory/backend/rules/README.md`](agent-memory/backend/rules/README.md) |
| Contributing (tests, Docker, model overview) | [`agent-memory/CONTRIBUTING.md`](agent-memory/CONTRIBUTING.md) |
| Service README (ports, API highlights, dev) | [`agent-memory/README.md`](agent-memory/README.md) |

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

Replace `OWNER/REPO` in the badge URLs at the top of this file with your GitHub org and repository name after publishing.
