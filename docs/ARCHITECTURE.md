# AGM Architecture

**Target reader:** senior engineer evaluating AGM as memory infrastructure for a multi-agent pipeline.

---

## 1. Problem Statement

LLM agent pipelines that persist memory across sessions have two attack surfaces that existing frameworks ignore.

**Memory poisoning** is the more obvious one: a compromised tool, a malicious peer agent, or a web-fetch endpoint injects false facts into the store. Retrieval-Augmented Generation pipelines then surface those facts with no indication they are suspect. The agent reasons on poisoned data and the corruption propagates forward through every subsequent session.

**Identity spoofing** is subtler. An agent that mimics another agent's name or UUID can write memories under a trusted identity. Nothing in standard RAG prevents this. The receiving system sees a valid agent ID and trusts the write.

Existing solutions ask the wrong question: "Is this content true?" That question requires ground truth AGM does not have. The better question — borrowed from immunology — is: "Does this content look dangerous in context?" Danger is detectable without knowing truth. A write-flood is dangerous regardless of content accuracy. A memory that contradicts everything a known agent has written is dangerous regardless of whether the contradiction is correct. A memory that arrives from a peer agent who has never established reputation is suspicious by default.

AGM operationalizes Polly Matzinger's Danger Theory as a first-class design primitive: the immune system does not distinguish self from non-self; it responds to damage signals. AGM does the same.

---

## 2. Design Philosophy

Matzinger's Danger Theory replaces the self/non-self distinction with a damage signal model. In the immune system, T-cells do not activate on antigen presentation alone — they require a co-stimulatory signal from a Dendritic Cell that has detected tissue damage. Without the danger signal, the T-cell enters a state called *anergy*: present but inert.

AGM maps this directly onto agent memory:

- **Anergy** is the default state of inter-agent and low-reality memories. They exist in the store but are invisible to normal queries and cannot influence reasoning until corroborated.
- **Dendritic Cell Agent (DCA)** monitors behavioral signals — write velocity, source diversity, reasoning coherence, trust cliffs — and emits danger context (SAFE / SEMI_MATURE / MATURE_DANGER).
- **Quorum** plays the role of MHC presentation: a memory's trust is multiplied by whether its owning agent has established consensus across three independent timescales.

These are not metaphors applied after the fact. The state machine, the trust formula, and the DCA scoring logic all derive directly from the biological model.

---

## 3. System Overview

```
  Agent Pipeline
       │
       │  MCP (14 tools) or REST
       ▼
┌─────────────────────────────────────────────┐
│              FastAPI  (main.py)             │
│  /agents  /memories  /trust  /stats         │
│  /graph   /violations  /notifications       │
│  /admin   /project                          │
└──────────────┬──────────────────────────────┘
               │
       ┌───────▼────────┐
       │  Rules Engine  │  ← RULE_001–RULE_013
       │  (checker.py)  │    runs after every write
       └───────┬────────┘
               │
       ┌───────▼────────┐
       │  Trust Engine  │  ← runs every 60 s (background)
       │ (trust_engine) │    exponential decay + anomaly penalties
       └──┬─────────────┘
          │                  ┌─────────────────┐
          ├─────────────────►│  DCA monitor    │  every 3 cycles
          │                  │ (dendritic_cell) │
          │                  └─────────────────┘
          │
   ┌──────▼──────────────────────────┐
   │  PostgreSQL + pgvector           │
   │  agents  memories  sessions      │
   │  rule_violations  provenance     │
   │  trust_metric_snapshots          │
   └──────────────────────────────────┘
          │
   ┌──────▼──────────────────────────┐
   │  Redis                           │
   │  trust cache (TTL)               │
   │  reconsolidation locks+snapshots │
   │  quorum signal cache             │
   │  DCA scan cache                  │
   │  vector clocks                   │
   │  notifications list              │
   └──────────────────────────────────┘

Background task schedule (trust_engine.py: start_trust_background_task):
  Every 60 s  → run_trust_pass → post_trust_maintenance
                 (promote_anergic, quarantine_contradicting, consolidate_memories,
                  compute_danger_signals)
  Every 180 s → DCA.run_population_scan  (every 3rd trust cycle)
```

---

## 4. The 8 Defense Mechanisms

### 4.1 Exponential Trust Decay
**Analog:** Memory consolidation — unread memories fade. **Defends against:** stale-data exploitation.

Every memory has a per-source decay rate λ applied as `trust = base × exp(-λ × hours)`. Rates from `trust_engine.py`: `tool_call=0.003`, `user_input=0.005`, `web_fetch=0.015`, `inter_agent=0.02`. Inter-agent memories decay 6.7× faster than tool-call memories. The background task runs every 60 seconds and updates all non-deleted memories.
**Key location:** `trust_engine.py: _compute_trust_score_components`

### 4.2 Dendritic Cell Agent (DCA)
**Analog:** Matzinger's Dendritic Cell tissue-damage signaling. **Defends against:** persistent behavioral compromise.

The DCA samples each recently-active agent and accumulates danger signals (weighted: reasoning_break=0.35, write_surge=0.2, source_collapse=0.15, trust_cliff_cluster=0.2, retrieval_anomaly=0.1) against safe signals (consistent_reasoning=0.3, low_write_velocity=0.2, source_diversity=0.2, corroboration_rate=0.3). If `danger_score > safe_score`, context is MATURE_DANGER and every memory written in the prior 30 minutes is auto-flagged. The fast signal in the Quorum system reads the DCA context directly, applying a 0.2× multiplier at MATURE_DANGER.
**Key location:** `dendritic_cell.py: DendriticCellAgent.sample_agent`
**Integrates with:** Quorum fast signal, trust decay, notifications.

### 4.3 Behavioral Hash + Drift Detection
**Analog:** MHC self-peptide presentation — immune cells recognise "self" by molecular fingerprint. **Defends against:** identity spoofing, sleeper-cell persona drift.

Each agent carries a rolling 10-dimensional behavioral vector (content length statistics, source distribution, write interval, flag rate, inter-agent fraction, safety context richness). After every write, a SHA256 hash of the vector is computed and compared to the stored baseline. Drift is a weighted sum: `0.2 × length_delta + 0.2 × source_JSD + 0.3 × interval_delta + 0.15 × flag_rate_delta + 0.15 × rest`. Drift > 0.4 pushes a HIGH notification and logs an anomaly event; RULE_011 checks the per-session write pattern against the baseline's μ ± 2σ bounds.
**Key location:** `lib/behavioral_hash.py: compute_behavioral_drift`, `rules/engine.py: _check_behavioral_drift`

### 4.4 Three-Signal Quorum Trust
**Analog:** T-cell co-stimulation — antigen alone is insufficient; a second signal from an APC is required for activation. **Defends against:** reputation laundering, new-agent impersonation.

Three independent signals with different half-lives gate every trust computation. Fast signal (5-minute half-life) reflects real-time write consistency and DCA context. Medium signal (2-hour half-life) evaluates session-level flag rate, average trust, and rule violation count. Slow signal (168-hour half-life) evaluates lifetime reputation — flag rate, average trust, session success rate, behavioral drift history, and weighted violation severity — floored at 0.10 so reputation never fully expires. Quorum status maps directly to a trust multiplier applied to every memory from that agent: FULL_QUORUM (all 3 > 0.6) → ×1.0; PARTIAL_QUORUM → ×0.7; FAILED_QUORUM → ×0.3.
**Key location:** `lib/quorum_trust.py: compute_quorum_score`

### 4.5 Reconsolidation Lock
**Analog:** Memory reconsolidation — retrieved memories are briefly labile and vulnerable to modification before re-storage. **Defends against:** concurrent read-modify-write injection.

When a memory is retrieved, `ReconsolidationGuard.locked_retrieval` takes a Redis snapshot (SHA256 of key fields, 300-second TTL) and acquires an exclusive lock (30-second TTL, 5-second acquire timeout). On lock release, the snapshot is compared to the current database row. Any change in `content`, `trust_score`, `is_flagged`, `flag_reason`, or `memory_state` during the retrieval window is logged as `reconsolidation_corruption` and raises a HIGH notification. The `flag_memory` MCP tool returns HTTP 409 if the memory is currently locked.
**Key location:** `lib/reconsolidation.py: ReconsolidationGuard.locked_retrieval`

### 4.6 Content Addressing (Tamper Detection)
**Analog:** DNA integrity checking — stored sequences have checksums; mismatches indicate damage. **Defends against:** storage-level tampering, database row modification outside the API.

At write time, a deterministic SHA256 is computed over pipe-joined canonical fields: `content|agent_id|session_id|source_type|source_identifier|created_at`. The hash is stored in `content_hash`. The `POST /admin/verify-integrity` endpoint and periodic background scans recompute the hash against the live row. A mismatch sets `content_hash_valid=False`, flags the memory, and pushes a CRITICAL notification.
**Key location:** `lib/content_address.py: compute_content_hash, verify_memory_integrity`

### 4.7 Vector Clocks + Causal Chain Validation
**Analog:** Temporal ordering in distributed systems — Lamport clocks prevent causality violations. **Defends against:** temporal phantom injection (memories that claim to follow events that never occurred).

Every memory stores a vector clock (JSONB, 24-hour Redis TTL) and a list of `causal_parents` — the last 5 memories read by this agent in the prior 10 minutes. Validation checks that (a) a non-first memory has declared parents, (b) no parent has a `created_at` after the child, and (c) the child's vector clock is not behind any parent's clock. RULE_012 fires on any validation failure with severity HIGH and auto-flag.
**Key location:** `lib/vector_clock.py: validate_causal_chain`

### 4.8 Memory State Machine (Anergy / Quarantine / Consolidation)
**Analog:** T-cell anergy, clonal deletion, and long-lived plasma cells. **Defends against:** poisoned memories entering the reasoning context, coordinated corroboration bypass.

The state machine is described in full in Section 6. It gates which memories are visible to agent reasoning: anergic and quarantined memories are excluded from the `get_safe_memories` retrieval path. RULE_013 returns HTTP 403 when `memory_state=anergic` is queried directly.
**Key location:** `trust_engine.py: determine_initial_memory_state, promote_anergic_memories, quarantine_contradicting_memories, consolidate_memories`

---

## 5. Trust Score Formula

```
trust = 1.0
      × exp(−λ × hours)           # time decay
      × source_reliability         # 0.5 if flagged, 1.0 otherwise
      × anomaly_penalty            # product of triggered anomaly penalties
      × utility_multiplier         # 0.8/1.0/1.2/0.6 by session outcome
      × reality_score_factor       # 0.3–1.0 from safety_context.reality_score
      × quorum_multiplier          # 0.3 / 0.7 / 1.0 by quorum status
```

**Decay rates (λ):** `tool_call`=0.003, `user_input`=0.005, `web_fetch`=0.015, `inter_agent`=0.02, default=0.01.

**Anomaly penalties** (multiplicative, stacked): write-flood=0.30, source-contradiction=0.50, trust-chain-contamination=0.40, rapid-modification=0.60.

**Reality score factor:** ≥0.9→1.0, ≥0.7→0.9, ≥0.5→0.6, <0.5→0.3.

**Utility multiplier:** session outcome `success`→1.2, `failed`→0.6, no read event→0.8, unknown→1.0.

**Worked example** — inter-agent memory, flagged once, PARTIAL_QUORUM, 48 hours old, never read, no reality score:

| Factor | Value | Calculation |
|--------|-------|-------------|
| Time decay | 0.383 | exp(−0.02 × 48) |
| Source reliability | 0.500 | flagged=True |
| Anomaly penalty | 1.000 | no anomaly triggers |
| Utility | 0.800 | no read event |
| Reality | 1.000 | no reality_score key |
| Subtotal | **0.153** | product of above |
| Quorum multiplier | 0.700 | PARTIAL_QUORUM |
| **Final trust** | **0.107** | 0.153 × 0.7 |

This memory is below the 0.6 threshold for `get_safe_memories` and will not appear in agent reasoning.

---

## 6. Memory State Machine

```
                      write (inter_agent OR reality_score < 0.3)
                            │
  write (default)           ▼
      ────────────►  [ ANERGIC ]
                            │
          ┌─────────────────┤
          │                 │
          │ 3+ distinct     │ semantically similar to
          │ trusted agents  │ 3+ active high-trust memories
          │ corroborate     │ (cosine dist < 0.15)
          ▼                 ▼
     [ ACTIVE ]      [ QUARANTINED ]
          │
          │ trust > 0.8 AND age > 24h
          │ AND was read AND session=success
          ▼
   [ CONSOLIDATED ]
```

State transitions are evaluated by the post-trust-maintenance pass that runs after every trust cycle (`trust_engine.py: _run_post_trust_maintenance`). There is no transition out of QUARANTINED or CONSOLIDATED in the current codebase. Soft deletion (`is_deleted=True`) is orthogonal to state and excludes memories from all processing.

---

## 7. The 13 Detection Rules

| Rule | Trigger | Severity | Defense response |
|------|---------|----------|-----------------|
| RULE_001 | Session write count > 50 | CRITICAL | Auto-flag memory, persist violation, CRITICAL notification |
| RULE_002 | Agent read ≥ 3 flagged memories in session | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_003 | Negated term in new memory appears positively in 3+ agent memories | MEDIUM | Persist violation (no auto-flag) |
| RULE_004 | 5+ provenance events on one memory within 10 minutes | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_005 | High-stakes keywords (delete/credentials/api key/etc.) without `human_verified=True` | MEDIUM | Persist violation (no auto-flag) |
| RULE_006 | `inter_agent` source written without a `session_id` | LOW | Persist violation (no auto-flag) |
| RULE_007 | `safety_context.context_expires_at` is in the past | MEDIUM | Persist violation (no auto-flag) |
| RULE_008 | Agent ID not found in `agents` table | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_009 | 5+ memories with ≥ 0.9 SequenceMatcher similarity in same session | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_010 | `trust_updated` event shows trust drop > 0.40 | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_011 | Session write count or avg content length deviates > 2σ from registered baseline | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_012 | `context_hash` missing/unknown, or causal chain validation fails | HIGH | Auto-flag memory, persist violation, HIGH notification |
| RULE_013 | Direct query for `memory_state=anergic` | CRITICAL | HTTP 403 returned; violation persisted at query time |

Rules run synchronously in `check_memory_rules` after every write. RULE_013 is the sole write-time stub that fires at query time; its `check()` function returns `None`.

---

## 8. Data Model

```
agents ──────────────────────────────────────────────────────┐
  id (PK)                                                     │
  name                                                        │
  behavioral_baseline (JSONB)   ← μ/σ for drift detection    │
  behavioral_vector (JSONB)     ← current 10-dim fingerprint  │
  behavioral_hash (SHA256)                                    │
  behavioral_drift_score                                      │
  system_prompt_hash                                          │
                                                              │
memories ─────────────────────────────────────────────────── ┤
  id (PK)                                                     │
  agent_id (FK → agents CASCADE)                             │
  content (TEXT)                                              │
  source_type / source_identifier                             │
  trust_score / is_flagged / flag_reason                      │
  memory_state (active|anergic|consolidated|quarantined)      │
  session_id                                                  │
  embedding (vector 1536)       ← pgvector similarity search  │
  safety_context (JSONB)        ← reality_score, context_hash │
  content_hash / content_hash_valid                           │
  causal_parents (JSONB)        ← list of parent memory UUIDs │
  vector_clock (JSONB)          ← Lamport-style clock map      │
  causal_depth (INT)                                          │
                                                              │
memory_provenance_log ──────────────────────────────────────  ┤
  memory_id (FK → memories CASCADE)                          │
  performed_by_agent_id (FK → agents SET NULL)               │
  event_type   (write/read/state_changed/trust_updated/       │
                anomaly_flagged/behavioral_hash_updated/…)    │
  event_metadata (JSONB)                                      │
  timestamp                                                   │
                                                              │
trust_metric_snapshots ─────────────────────────────────────  ┤
  memory_id (FK → memories CASCADE)                          │
  trust_score / time_decay_factor                             │
  source_reliability_factor / anomaly_penalty                 │
  quorum_fast/medium/slow_signal / quorum_status              │
  snapshot_reason                                             │
                                                              │
rule_violations ─────────────────────────────────────────────┘
  memory_id (FK → memories CASCADE, nullable)
  agent_id (FK → agents SET NULL, nullable)
  rule_name / severity / description
  is_acknowledged / acknowledged_by / acknowledged_at
  auto_flagged
```

---

## 9. MCP Integration

The `agm_memory_mcp` package exposes 14 tools over the Model Context Protocol. All tools delegate to `AgentMemoryClient`, which wraps the REST API.

| Tool | Maps to | Notes |
|------|---------|-------|
| `register_agent` | `POST /agents` | Call once at agent startup; store returned UUID |
| `write_memory` | `POST /memories` | Returns initial trust, state, content_hash, quorum status |
| `read_memory` | `GET /memories/{id}` | Acquires reconsolidation lock during retrieval |
| `query_memories` | `GET /memories` | Do not pass `memory_state=anergic` — triggers RULE_013 (403) |
| `get_safe_memories` | `GET /memories/safe` | Pre-filtered: active, not flagged, trust ≥ 0.6 |
| `get_trust_score` | `GET /memories/{id}/trust` | Live recomputed value |
| `get_provenance` | `GET /memories/{id}/provenance` | Full event audit trail |
| `flag_memory` | `POST /memories/{id}/flag` | Returns 409 if reconsolidation-locked |
| `check_violations` | `GET /violations/{id}` | Per-memory rule violations |
| `acknowledge_violation` | `POST /violations/{id}/acknowledge` | Human review workflow |
| `run_rules_check` | triggers rules evaluation | Force re-check when context changed |
| `consolidate_memories` | `POST /admin/consolidate` | Manual trigger; runs on schedule otherwise |
| `get_notifications` | `GET /notifications` | Last 20 alerts: DCA, drift, integrity, trust-cliff |
| `get_rules_reference` | embedded (no API call) | Returns all 13 rules from package; no network needed |

**Typical pipeline pattern:**
1. `register_agent` → store `agent_id`
2. Before each task: `get_safe_memories(agent_id=…)` to load context
3. During task: `write_memory(source_type="tool_call", …)` for each outcome
4. Agent-to-agent: `write_memory(source_type="inter_agent", …)` → memory starts anergic
5. Periodically: `get_notifications()` to surface active security events
6. If memory is flagged: `check_violations(memory_id)` → `acknowledge_violation` after human review

---

## 10. Novel Research Contributions

### 10.1 Dendritic Cell Algorithm Applied to LLM Memory (Implemented)

**What existed:** The Dendritic Cell Algorithm (Greensmith et al., 2005) was designed for network intrusion detection over numeric system-call traces.

**What AGM adds:** AGM applies DCA to the semantic domain of LLM agent behavior. The safe/danger signal inputs are derived from embedding cosine similarity (reasoning coherence), write velocity, source type entropy, and trust-cliff clustering in Redis. The DCA context is fed directly into the quorum fast-signal as a multiplier (0.2× at MATURE_DANGER, 0.7× at SEMI_MATURE), making it mechanistically integrated into trust scoring rather than a separate reporting layer.

**Where to look:** `dendritic_cell.py: DendriticCellAgent`, `lib/quorum_trust.py: compute_fast_signal`

### 10.2 Vector Clocks in Retrieval-Augmented Memory (Implemented)

**What existed:** Vector clocks are standard in distributed databases (Dynamo, Riak) for conflict detection. RAG systems use similarity search with no causal ordering.

**What AGM adds:** Every memory stores a Lamport-style vector clock (per-agent counter map) and declares `causal_parents` — the memories it observed before being written. This enables detection of *temporal phantoms*: memories that claim causal descent from events that occurred after them, or whose clocks regress behind their declared parents. This is a novel application of distributed systems consistency primitives to the problem of fabricated memory provenance.

**Where to look:** `lib/vector_clock.py: validate_causal_chain`, `rules/engine.py: _check_causal_orphan`

### 10.3 VCG Incentive Mechanism for Corroboration (Unimplemented)

A Vickrey-Clarke-Groves mechanism could replace the current fixed-threshold corroboration rule (3 distinct agents) with a market where agents bid reputation to corroborate anergic memories. Agents whose corroboration is later confirmed (memory proves useful in successful sessions) gain reputation; those whose corroboration precedes eventual quarantine lose it. This would make the promotion threshold self-calibrating and resistant to sybil corroboration attacks without requiring a trusted third party to set thresholds. Not currently implemented.

---

## 11. Known Limitations

**Contradiction detection is regex-based.** RULE_003 and the trust engine's `source_inconsistency` trigger use `re.compile(r"\b(?:not|never|no|…)\s+([a-z][a-z0-9_-]{2,})\b")`. This misses semantic contradictions that do not use explicit negation markers and will false-positive on idioms ("not bad" = good). A sentence-embedding contradiction classifier would be more robust.

**3D graph rendering does not scale past a few hundred nodes.** The graph page uses `react-force-graph-3d` with all nodes and edges loaded client-side. At production memory volumes (thousands of nodes), the initial layout computation will hang the browser. Pagination or server-side layout pre-computation is not implemented.

**No APM instrumentation.** There is no OpenTelemetry, Prometheus, or Datadog integration. Observability is limited to Python `logging` module output. Trust-cycle latency and rules-engine throughput are not tracked. Adding a `/metrics` endpoint would require instrumentation work.

**Quorum slow signal cold-start problem.** New agents have no behavioral history, so `compute_slow_signal` returns 0.5 and decays from there with a 168-hour half-life. A genuinely new legitimate agent will have its memories scored at PARTIAL_QUORUM for the first several hours, applying a ×0.7 trust multiplier to all its writes. This is by design but may surprise operators onboarding trusted agents.

**RULE_013 is enforced at query time only.** The `_check_anergy_bypass_attempt` rule check function in `rules/engine.py` unconditionally returns `None`; enforcement is handled separately in the memories router. Batch violation scans via `collect_violations` will not surface RULE_013 violations for already-stored anergic memories.
