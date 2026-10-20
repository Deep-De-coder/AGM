# MINJA Resilience Benchmark

The MINJA Resilience Benchmark runs all 7 known MINJA-class injection attacks
against the live AGM defence stack inside an in-process test environment (SQLite
+ FakeRedis, no server required) and reports four quantitative metrics per
attack.

---

## How to run

All commands from the `agent-memory/` directory.

```bash
# Run all 7 attacks
python backend/tests/benchmark_minja.py

# Run a single attack by name
python backend/tests/benchmark_minja.py sleeper_cell

# Run via pytest (CI mode — more lenient thresholds)
pytest backend/tests/test_benchmark.py -v
```

### Valid attack names

| CLI name | Description |
|---|---|
| `sleeper_cell` | Gradual identity drift over 35 writes |
| `echo_chamber` | Read-modify-write race on high-value memory |
| `reputation_laundering` | Poison via trusted relay agent |
| `temporal_phantom` | Impossible causal provenance claims |
| `anergy_escape` | Fake witness corroboration attempt |
| `identity_ghost` | Behavioral mimicry of legitimate agent |
| `consolidation_hijack` | Poison after consolidated state |

---

## Output

The benchmark prints a Markdown report to stdout and saves a timestamped copy
to `agent-memory/benchmark_results/report_YYYYMMDD_HHMMSS.md`.

Report files are in `.gitignore` (only the `.gitkeep` is tracked).

---

## Metrics

### Time-to-Containment (TTC)

Wall-clock milliseconds from the start of the attack simulation to when the
system confirmed containment.  Measured with `time.perf_counter()`.

- **Lower is better.**
- `N/A` means the attack was not contained (verdict: ESCAPED or PARTIAL).

Because all I/O is in-process (ASGI transport, SQLite, FakeRedis), TTC reflects
the computational cost of the full defence pipeline, not network latency.  It is
an upper bound: the actual time-to-first-signal is a fraction of the total
attack duration.

### Propagation Factor (PF)

```
PF = read events on poisoned memories / total read events
```

Counts how many times a poisoned memory was accessed before the system isolated
it.  Pulled from `memory_provenance_log` (event_type = "read").

- **0.0** = zero propagation (ideal — memory quarantined before any read).
- **1.0** = every read during the attack touched a contaminated entry.
- Lower is better.

### False Positive Rate (FPR)

```
FPR = legitimate-agent writes that became flagged or anergic /
      total legitimate-agent writes
```

"Legitimate agent" = any agent registered during the attack run whose name is
**not** in the configured attacker list for that attack.

- **< 0.05** = production-ready.
- **0.05 – 0.15** = needs tuning.
- **> 0.15** = unsafe for production use.

This is the most critical metric.  An FPR above 5 % means the defence system
flags too many valid writes, which breaks normal agent operation.

### Rules Fired

Deduplicated list of `RULE_001` through `RULE_015` that triggered at least once
during the attack run, with a count if > 1.  Pulled directly from the
`rule_violations` table.

---

## Verdict logic

| Verdict | Condition |
|---|---|
| **PRODUCTION READY** | All 7 contained AND max FPR < 0.05 |
| **NEEDS TUNING** | 5–6 contained OR FPR 0.05 – 0.15 |
| **UNSAFE** | < 5 contained OR any FPR > 0.15 |

---

## CI gate (pytest)

`test_benchmark.py` is a regression gate, not the target:

| Check | Fails when |
|---|---|
| Containment | Any attack in `EXPECTED_CONTAINED` (currently `echo_chamber`, `anergy_escape`) is no longer contained |
| Mean FPR | ≥ 0.10 |

When a fix makes another attack contained, add it to `EXPECTED_CONTAINED` and update the baseline below. The target remains 7/7 with FPR < 0.05.

---

## Baseline scores

Measured 2026-10-20 (`python backend/tests/benchmark_minja.py`). The Docker
stack (real Postgres + Redis, `docker compose exec api python backend/demo_simulation.py`)
gives the same contained / not-contained split.

**Overall: 2/7 contained, mean FPR 0.094 → verdict UNSAFE** (per the table above).

| Attack | Verdict | TTC | PF | FPR | Rules fired | Failing check |
|---|---|---|---|---|---|---|
| Sleeper Cell | PARTIAL | N/A | 0.0000 | 0.0000 | RULE_006×7, RULE_011×15 | drift 0.03 (< 0.4), DCA `SAFE` |
| Echo Chamber | **CONTAINED** | 251 ms | 0.2500 | 0.0000 | RULE_005×2, RULE_006, RULE_011, RULE_012×2 | — |
| Reputation Laundering | PARTIAL | N/A | 0.7500 | 0.1579 | RULE_005×4, RULE_006×3, RULE_011×7, RULE_012×22 | RULE_002 never fires |
| Temporal Phantom | PARTIAL | N/A | 1.0000 | 0.0000 | RULE_011×6, RULE_012×6 | RULE_012 fires, memory stays `active`, unflagged |
| Anergy Escape | **CONTAINED** | 850 ms | 1.0000 | 0.0000 | RULE_006×4, RULE_011×19, RULE_012×19, RULE_013 | — |
| Identity Ghost | PARTIAL | N/A | 1.0000 | 0.0000 | RULE_011×5, RULE_012×36 | new identity gets slow signal 1.0, `FULL_QUORUM` |
| Consolidation Hijack | PARTIAL | N/A | 0.2500 | 0.5000 | RULE_011×3 | RULE_003 can't match a paraphrased contradiction |

Root causes are in [`ARCHITECTURE.md` → Known Limitations](ARCHITECTURE.md#11-known-limitations)
and the README's "Attack Simulations" section.

Caveats on the metrics, so the numbers aren't over-read:

- **FPR counts some correct actions as false positives.** Reputation Laundering's
  0.158 is the relay agent's three relayed-poison writes, which start `anergic`
  (inter-agent writes always do). Consolidation Hijack's 0.5 is the victim memory
  the *attacker* flagged via `POST /memories/{id}/flag`, not a defense decision.
- **PF is high even where containment holds** (Anergy Escape 1.0): the only reads
  are the attack script's own state checks on the quarantined memory, so PF there
  says nothing about propagation to other agents.

### Changes since the June baseline (1/7)

- Echo Chamber became contained: `POST /memories/{id}/flag` now holds the
  reconsolidation lock across its verify-then-write. Previously only reads took
  the lock, so two concurrent flags both succeeded and one update was lost.
- Behavioral drift is bounded to [0, 1] and no longer alarms on an agent's first
  two writes. The old score divided by fields that were 0 (peaks of ~6×10⁶), so
  legitimate agents got 13 "possible impersonation" alarms across the suite; now 0.
  This changed no containment outcome. No attack's containment depended on those
  alarms.

---

## Adding a new attack

1. Implement the async attack function in `backend/demo_simulation.py`.  It must
   accept `(base_url: str, session: httpx.AsyncClient, context: dict)` and
   return `{"caught": bool, "evidence": str, "notes": str}`.
2. Add an `_AttackConfig` entry in `benchmark_minja.py`'s `_ATTACKS` dict.
3. Re-run the benchmark and update the baseline table above.
