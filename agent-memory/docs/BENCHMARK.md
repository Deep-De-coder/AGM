# AGM Benchmark & Ablation Documentation

## MINJA Resilience Benchmark

The MINJA (Memory INJection Attack) benchmark evaluates the AGM defense stack
against 7 canonical adversarial memory manipulation attacks.  Each attack runs
in a fully isolated SQLite + FakeRedis environment; state never bleeds between
runs.

### Running the benchmark

```bash
# All 7 attacks
python backend/tests/benchmark_minja.py

# Single attack by name
python backend/tests/benchmark_minja.py sleeper_cell
```

### Attack inventory

| # | Name | Key defense(s) | Biological analog |
|---|------|---------------|-------------------|
| 1 | Sleeper Cell | Behavioral Hash + DCA | Slow-burn latent compromise |
| 2 | Echo Chamber | Content Hash + Reconsolidation | Read-modify-write race |
| 3 | Reputation Laundering Relay | Quorum Trust + Taint | Trust laundering via relay |
| 4 | Temporal Phantom | Vector Clocks | Orphaned causal chain |
| 5 | Anergy Escape | Two-Signal Anergy + Quorum | Fake corroboration escape |
| 6 | Identity Ghost | Behavioral Hash + Rules | Agent impersonation |
| 7 | Consolidation Hijack | Content Hash + Reconsolidation | Consolidation-phase forgery |

### Metrics

- **Containment** — whether the defense stack fully contained the attack
- **TTC (Time-to-Contain)** — milliseconds from attack start to first signal (N/A if escaped)
- **Propagation Factor** — read events on poisoned memories / total read events (lower is better)
- **False Positive Rate** — flagged legitimate writes / total legitimate writes (< 0.05 for production)
- **Rules Fired** — which `RULE_XXX` predicates triggered during the run

---

## Defense Ablation Testing Framework

Mechanistic interpretability for the AGM defense stack: systematically disable
each of the 8 defense mechanisms one at a time to measure which defenses are
independently necessary for containing each of the 7 attacks.

### Concept

An **ablation** run applies one toggle (a set of `unittest.mock.patch` calls
that no-op a specific defense) and then runs the full attack.  No production
code is modified; patches are applied only for the duration of each run.

The **escaped due to ablation** flag for a `(defense, attack)` cell is:

```
escaped_due_to_ablation = baseline_contained AND NOT contained_with_defense_disabled
```

### Defense toggles

| ID | Display Name | What is disabled |
|----|-------------|-----------------|
| `dca` | Dendritic Cell Algorithm | Population-level danger signals; agent context always reports `MATURE_SAFE` |
| `behavioral_hash` | Behavioral Hash | Rolling behavioral drift detection always reports 0.0 drift |
| `quorum` | Quorum Trust | Corroboration gate always returns `FULL_QUORUM` with 1.0 multiplier |
| `content_address` | Content-Addressed Storage | Hash integrity checks always return valid |
| `reconsolidation` | Reconsolidation Guard | Write-lock acquisition and snapshot verification always succeed |
| `vector_clock` | Vector Clocks | Causal chain validation always reports valid |
| `two_signal_anergy` | Two-Signal Anergy | All memories start in `active` state regardless of taint signals |
| `rules_engine` | Rules Engine | All predefined rules suppressed; no violations persisted |

### Running the ablation suite

```bash
# Full 8 × 7 = 56 ablation runs + baseline (slow — ~10 min)
python -m backend.tests.ablation_runner

# Ablate only one defense across all 7 attacks
python -m backend.tests.ablation_runner --defense dca

# Ablate all defenses against one attack
python -m backend.tests.ablation_runner --attack sleeper_cell

# Save outputs
python -m backend.tests.ablation_runner --output-md results/ablation.md --output-json results/ablation.json
```

### Reading the ablation matrix

```
| Defense          | Sleeper Cell | Echo Chamber | ... |
|------------------|-------------|--------------|-----|
| dca              | ❌          | ✅           | ... |
| behavioral_hash  | ❌          | ✅           | ... |
| rules_engine     | ✅          | ❌           | ... |
```

- **❌** — the attack escaped when this defense was disabled (defense is critical for this attack)
- **✅** — the attack was still contained even without this defense (redundant / overlapping coverage)
- **—** — not tested in this run

### Key outputs from `AblationResult`

| Method | Returns |
|--------|---------|
| `critical_defenses()` | `{attack_name: [mechanism_id, ...]}` — per-attack critical dependencies |
| `defense_contribution()` | `{mechanism_id: float}` — % of baseline-contained attacks that escape |
| `redundant_defenses()` | `[mechanism_id, ...]` — defenses with 0% independent contribution |

### Automated tests

Six unit tests in `backend/tests/test_ablation.py` cover the framework without
running the full 56-cell matrix:

| Test | What it verifies |
|------|-----------------|
| `test_toggle_registry_complete` | 8 toggles, unique IDs, each has ≥ 1 patch |
| `test_single_ablation_runs_without_crash` | DCA toggle × sleeper_cell completes without exception |
| `test_baseline_matches_benchmark` | Runner baseline and `MINJABenchmark.run_all()` return same set of attacks |
| `test_ablation_cell_logic` | `escaped_due_to_ablation` property edge cases |
| `test_critical_defenses_computation` | `critical_defenses()`, `defense_contribution()`, `redundant_defenses()` |
| `test_report_generation_no_crash` | `generate_ablation_report()` returns a valid Markdown string with all required headers |

### Interpreting results

- A defense with **high contribution** (close to 100%) is a single point of failure: if it
  breaks, many attacks escape.  These deserve extra monitoring and fallback logic.
- A defense with **0% contribution** (redundant) may still be valuable as a second
  layer — its absence only matters when another defense also fails simultaneously.
- Attacks with **multiple critical defenses** are better protected: an attacker must
  bypass all of them simultaneously to succeed.
