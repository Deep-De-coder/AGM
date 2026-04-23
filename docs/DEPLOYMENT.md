# Deployment and Runtime Requirements

Overview and Quick Start: [`README.md`](../README.md).

This document summarizes how **PostgreSQL**, **Redis**, and **environment variables** fit together for AGM (agent-memory). It aligns with `agent-memory/docker-compose.yml`, `agent-memory/.env.example`, and the “Local development” section of [`agent-memory/README.md`](../agent-memory/README.md).

## Docker Compose (Recommended)

- Compose starts **PostgreSQL (pgvector)**, **Redis**, the **API**, and the **dashboard** together.
- The `api` service receives **`DATABASE_URL`** and **`REDIS_URL`** from `docker-compose.yml`. You do **not** need to copy `.env` or set a custom DB URL for the default stack to work.
- Postgres is initialized with database **`agentmemory`** (see `POSTGRES_DB` in compose). You do not create the database manually for this path.

## Running the API without Docker

- You need **PostgreSQL 16+ with pgvector** and **Redis 7+** running and reachable from the machine that runs the API.
- Copy **`agent-memory/.env.example`** to **`agent-memory/.env`** and set **`DATABASE_URL`** and **`REDIS_URL`** to match your instances. Run **Alembic** migrations before serving traffic (see [`agent-memory/README.md`](../agent-memory/README.md) — “Database migrations”).
- There is **no supported “no database”** mode for the real FastAPI service in production. Tests may use SQLite via pytest; that is not a substitute for running the stack for users.

## MCP or dashboard only (no local database)

- If you use **`agent-memory-mcp`** or any HTTP client against **an API someone else hosts**, you only configure **`AGENT_MEMORY_API_URL`** (and optional prefix). You are not required to run Postgres yourself in that scenario; the operator of that deployment provides the database.

## LLM / embedding API keys

- The AGM **HTTP API** does not require OpenAI, Anthropic, or similar keys in `.env`. Optional memory embeddings are supplied by clients if used; the service does not call external embedding APIs with a project-owned key by default.
