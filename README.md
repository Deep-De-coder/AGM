# AGM — Agent Memory

This repository includes the **agent-memory** service: a FastAPI backend with PostgreSQL (pgvector), Redis, a **trust decay and anomaly detection engine** that runs every 60 seconds, and a **React dashboard** for live metrics and a provenance graph.

## Architecture

```
                         ┌─────────────────────┐
                         │   Browser ( :3000 ) │
                         │  Vite React + nginx │
                         └──────────┬──────────┘
                                    │ HTTP (VITE_API_URL)
                                    ▼
┌──────────────┐   cache    ┌───────────────────────────────────┐
│    Redis     │◄──────────│         FastAPI API (:8000)       │
│ trust / keys │           │  memories · agents · stats · graph │
└──────────────┘           │  admin/run-trust-decay · trust_eng │
       ▲                   └────────────────┬──────────────────┘
       │                                    │
       │ async                                SQLAlchemy async
       │                                    ▼
       │                   ┌───────────────────────────────────┐
       │                   │  PostgreSQL + pgvector (:5432)    │
       │                   │  memories · agents · provenance   │
       │                   │  trust_metric_snapshots (history) │
       └───────────────────┴───────────────────────────────────┘

Background: every 60s the trust engine recalculates trust_score for all
non-deleted memories (decay + anomaly penalties), logs events, and updates Redis.
```

### Trust score (engine)

`trust_score = base_score × time_decay × source_reliability × anomaly_penalty`

- `base_score = 1.0`
- `time_decay = exp(-decay_rate × hours_since_creation)` with source-specific `decay_rate`
- `source_reliability = 0.5` if `is_flagged`, else `1.0`
- `anomaly_penalty`: product of penalties when rules trigger (write flood, contradiction heuristics, flagged-read contamination, rapid provenance bursts)

## Run everything (Docker)

From the **`agent-memory`** directory:

```bash
cd agent-memory
docker compose up --build
```

- **API:** [http://localhost:8000](http://localhost:8000) — OpenAPI docs at `/docs`
- **Dashboard:** [http://localhost:3000](http://localhost:3000) — static build served by nginx (built with `VITE_API_URL=http://localhost:8000`)

Ensure nothing else is bound to ports `5432`, `6379`, `8000`, or `3000`, or adjust the published ports in `agent-memory/docker-compose.yml`.

## Demo simulation (~2 minutes)

With Postgres and Redis running and the API up (local or Docker):

```bash
cd agent-memory
# Windows PowerShell:
$env:PYTHONPATH = "$PWD"; python backend/demo_simulation.py

# macOS / Linux:
PYTHONPATH=. python backend/demo_simulation.py
```

The script registers three agents, writes 20 memories with mixed `source_type` values, then issues a **flood** of additional writes in the same session so the **write-rate anomaly** fires when trust decay runs. It prints summary stats and sample trust scores.

Optional: `MEMORY_API_URL` points at the API (default `http://localhost:8000`).

## Project layout

| Path | Role |
|------|------|
| `agent-memory/backend/` | FastAPI app, SQLAlchemy models, `trust_engine.py`, routers |
| `agent-memory/frontend/` | Vite + React + TypeScript dashboard |
| `agent-memory/docker-compose.yml` | Postgres, Redis, API, nginx frontend |
| `agent-memory/requirements.txt` | Python dependencies |

## API highlights

| Endpoint | Purpose |
|----------|---------|
| `POST /admin/run-trust-decay` | Run one full trust recalculation (testing) |
| `GET /stats/summary` | Totals, flagged count, average trust, agent count |
| `GET /stats/trust-history` | Snapshots for the trust-over-time chart |
| `GET /graph` | Nodes/edges for the React Flow graph |
| `GET /agents` | Agent registry with per-agent aggregates |

## Development (without Docker)

**Backend** (from `agent-memory`, with local Postgres + Redis matching `DATABASE_URL` / `REDIS_URL` in `.env`):

```bash
pip install -r requirements.txt
set PYTHONPATH=%CD%   # Windows cmd
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (from `agent-memory/frontend`):

```bash
npm install
# optional: echo VITE_API_URL=http://localhost:8000 > .env
npm run dev
```

The dev server defaults to port `5173` and talks to `VITE_API_URL` or `http://localhost:8000`.
