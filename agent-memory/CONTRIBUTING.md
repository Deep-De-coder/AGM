# Contributing to Agent Memory

## Adding a new policy rule

Follow **Adding a custom rule** in [`backend/rules/README.md`](backend/rules/README.md), then:

1. Implement `_check_*` and append a `Rule(...)` to `PREDEFINED_RULES` in [`backend/rules/engine.py`](backend/rules/engine.py).
2. Extend `RuleContext` / [`backend/rules/checker.py`](backend/rules/checker.py) only if the rule needs new context fields.
3. Add a unit test in `backend/tests/test_rules.py` (or a dedicated file) and run the suite locally.

## Run tests locally

From the `agent-memory` directory (repository root for this service):

```bash
pip install -r requirements.txt
# Windows PowerShell
$env:PYTHONPATH = "$PWD"
# macOS / Linux
export PYTHONPATH=.
pytest backend/tests/ -v --tb=short
```

Lint (same layout as CI):

```bash
ruff check backend/
ruff format --check backend/
```

## Run the full stack with Docker Compose

```bash
cd agent-memory
docker compose up --build
```

- API: `http://localhost:8000` (OpenAPI: `/docs`)
- Dashboard (if enabled in compose): `http://localhost:3000`

Ensure ports `5432`, `6379`, `8000`, and `3000` are free or adjust `docker-compose.yml`.

## Data model and provenance flow

```
  Agent                    Memory                      Provenance
+-------+                +---------+                  +------------------+
| id    |--- 1:N ------>| agent_id|                  | memory_id (FK)  |
| name  |                | content |                  | event_type       |
| meta  |                | trust   |<-- audit ------| performed_by     |
+-------+                | session |                  | event_metadata   |
                         +---------+                  | timestamp        |
                               |                      +------------------+
                               +---- may reference ----> Agent (optional)
```

Typical flow:

1. **Register agent** → row in `agents`.
2. **Write memory** → row in `memories`, initial `trust_score`, and a provenance row with `event_type=write`.
3. **Read memory** → additional provenance row with `event_type=read` (and optional reader attribution).
4. **Trust engine** (scheduled or `/admin/run-trust-decay`) → updates `trust_score`, may append `trust_updated` / `anomaly_flagged`, and writes rows to `trust_metric_snapshots`.
5. **Rules engine** (after write or explicit check) → may insert `rule_violations` when policies fire.

Soft delete keeps the row in `memories` and logs `event_type=deleted` instead of erasing data.
