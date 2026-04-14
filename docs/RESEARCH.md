# AgentMemory: Provenance-Tagged Memory Infrastructure
# for Multi-Agent AI Systems

Long-form design and research notes. **Project entry point:** [`README.md`](../README.md) (single readme at repo root).

---

## SECTION 1: THE PROBLEM

Multi-agent systems fail in production for a predictable reason: they treat memory as a passive store instead of an adversarial surface. Memory poisoning in agent pipelines is the process of injecting plausible but malicious records into shared memory so that later retrieval produces unsafe actions with high confidence. Once poisoned entries are retrieved and re-written by downstream agents, contamination compounds into a trust chain problem rather than a single bad record problem.

This is not a theoretical concern. Recent work on MINJA reports injection success rates above 95% under realistic multi-agent conditions, including settings where attackers do not need to break authentication. The operational lesson is uncomfortable: authenticated does not mean safe, and retrieval quality does not imply memory integrity.

Current memory systems are optimized for recall, not adversarial resilience. MemGPT, Mem0, and HippoRAG provide useful abstractions for storage and retrieval but do not model memory states such as anergy or quarantine, do not attach trust provenance as first-class metadata, do not enforce causal ordering across writes, and do not maintain behavioral identity fingerprints for writing agents. This leaves them structurally vulnerable to attacks that look semantically valid.

The identity model is also incomplete. OAuth tokens and API keys answer one narrow question: who presented credentials. They do not answer a harder question that matters in agent ecosystems: what harm is this agent causing over time, despite valid credentials. In high-autonomy pipelines, this gap is where most practical compromise lives.

AgentMemory starts from a different premise, grounded in Polly Matzinger's Danger Theory (1994): biological immune systems do not primarily react to foreignness; they react to damage signals. Translated to agent memory, this means defense should monitor behavioral and structural damage patterns, not only identity claims.

At small scale, a poisoned memory is a bug. At large scale, where many agents read, write, summarize, and re-propagate shared state, poisoned memory becomes an amplification channel. That is why memory infrastructure requires provenance, trust dynamics, and containment states, not just vector search and long context.

---

## SECTION 2: WHAT THIS IS NOT

AgentMemory is not a general-purpose memory library, and it is not a drop-in replacement for MemGPT or Mem0. It is memory infrastructure for multi-agent pipelines that require auditability, trust provenance, causal integrity checks, and anomaly containment on shared memory. If your use case is single-agent convenience memory or simple retrieval augmentation without adversarial assumptions, a lighter system is likely the better choice.

---

## SECTION 3: ARCHITECTURE OVERVIEW

### 3.1 Core Concepts Table

| Concept | Biological Analog | What It Does |
|---|---|---|
| Memory States (`active` / `anergic` / `consolidated` / `quarantined`) | T-cell anergy | Untrusted memories are stored but excluded from reasoning until corroborated |
| Trust Decay (SHY model) | Synaptic homeostasis | Utility-based decay: battle-tested memories resist decay; unused ones do not |
| Behavioral Hash | MHC Class I display | Continuous identity fingerprint where behavior is part of credentialing |
| Dendritic Cell Agent | Matzinger's Danger Theory | Detects damage patterns independent of authentication identity |
| Quorum Sensing | Bacterial quorum sensing | Three-timescale trust signals must align for full influence |
| Vector Clocks | Distributed systems | Causal ordering prevents impossible provenance chains |
| Content-Addressed Storage | Git/Merkle trees | SHA256 object identity enables tamper detection |
| Reconsolidation Lock | Neuroscience reconsolidation | Retrieval-window lock blocks concurrent modification races |
| Two-Signal Activation | T-cell co-stimulation | Anergy exit requires corroborative signals, not a single write |
| 13 Detection Rules | Innate immune response | Pattern-based first-pass anomaly filter with graded severity |

### 3.2 Data Flow Diagram

```text
Agent Write Request
      |
      v
[1] determine_initial_state()    -> anergic if inter_agent / low reality
      |
      v
[2] compute_content_hash()       -> SHA256(content+metadata+timestamp)
      |
      v
[3] compute_causal_parents()     -> vector clock increment
      |
      v
[4] DB INSERT (memory created)
      |
      v
[5] update_behavioral_hash()     -> rolling fingerprint updated
      |
      v
[6] check_memory_rules()         -> 13 rules (background)
      |
      v
[7] update_quorum_tracker()      -> fast signal Redis update
      |
      v
[8] DCA context check            -> flag/anergic if MATURE_DANGER
      |
      v
Response returned to agent

Background (every 60s):
[B1] Trust decay (SHY + quorum multiplier)
[B2] promote_anergic_memories()
[B3] quarantine_contradicting()
[B4] consolidate_memories()
[B5] DCA population scan (every 3rd cycle)
[B6] compute_danger_signals()

Read Request
      |
      v
[R1] Reconsolidation lock acquired
[R2] content_hash verified
[R3] causal chain validated
[R4] trust score recomputed (if stale)
[R5] live quorum checked
[R6] snapshot taken
[R7] lock released
      |
      v
Response with full integrity metadata
```

### 3.3 Memory State Machine

```text
       WRITE
         |
         v
   +----------------+
   | if inter_agent |
   | or reality<0.3 |--------------------------+
   | or FAILED quorum|                         v
   | or MATURE_DANGER|               +--------------------+
   +----------------+                |      ANERGIC       |
         |                           |  (stored, not used |
         v                           |   in reasoning)    |
   +----------------+                +--------------------+
   |     ACTIVE     |                       |        |
   |   (default)    |            3+ trusted |        | contradicts
   +----------------+            corroborate |        | 3+ active
         |                                  v        v
         | trust>0.8                     ACTIVE   QUARANTINED
         | retrieved+success                       (flagged,
         | age>24h                                  excluded)
         v                                           |
   +----------------+                                |
   |  CONSOLIDATED  |<-------------------------------+
   |  (long-term    |   (never from quarantined
   |   trusted)     |    - dead end)
   +----------------+
```

---

## SECTION 4: THE 6 DEFENSE MECHANISMS

### 4.1 Dendritic Cell Agent (Danger Model)
**Biological/mathematical analog:** Matzinger's Danger Theory and the Dendritic Cell Algorithm lineage (Aickelin/Greensmith).  
**Attack it catches:** Authenticated agents that remain credential-valid while causing damage patterns, including MINJA-style memory contamination where identity checks pass.  
**Why existing systems miss it:** Most memory systems evaluate identity at authentication boundaries and do not continuously score post-auth behavior.  
**Implementation:** AgentMemory computes weighted danger and safe signals from live memory activity. Danger signals include reasoning breaks, write surges, source collapse, trust-cliff clustering, and retrieval anomalies. Safe signals include consistent reasoning, low write velocity, source diversity, and corroboration rate. The result is a per-agent context state (`SAFE`, `SEMI_MATURE`, `MATURE_DANGER`) updated in background scans; writes from `MATURE_DANGER` contexts are downgraded or flagged.  
**Limitation:** Signal quality depends on observed behavior volume. Very early writes (roughly the first 5 to 10 events) have limited statistical context, so early drift can be underpowered.

### 4.2 MHC Rolling Behavioral Hash
**Biological/mathematical analog:** MHC Class I antigen presentation as continuous identity evidence over time.  
**Attack it catches:** Credential theft, gradual compromise, and behavioral impersonation where static credentials are still valid.  
**Why existing systems miss it:** Static auth artifacts (keys/tokens) do not encode behavioral continuity; they confirm possession, not conduct.  
**Implementation:** Each agent maintains a rolling behavioral vector (10 dimensions: content length statistics, source distribution, write intervals, session/flag rates, and related telemetry). The vector is hashed (`SHA256`) and compared against baseline to produce a drift score. Drift above threshold (`>0.4`) triggers high-severity alerts and provenance events (`behavioral_hash_updated` plus anomaly metadata).  
**Limitation:** A skilled adversary can mimic short-window behavior distributions. This mechanism is strongest when combined with quorum slow-signal reputation, not used in isolation.

### 4.3 Multi-Timescale Quorum Sensing
**Biological/mathematical analog:** Quorum signaling with heterogeneous signal persistence windows.  
**Attack it catches:** Attacks tuned to evade single-window detectors: burst-and-reset patterns, new-identity mimicry, and short-session laundering.  
**Why existing systems miss it:** Existing memory stacks typically treat trust as scalar and immediate, without decoupled temporal channels.  
**Implementation:** AgentMemory computes `fast`, `medium`, and `slow` trust signals with half-lives of approximately 5 minutes, 2 hours, and 7 days. Full influence requires all three signals above threshold (`0.6`). Quorum status maps to multipliers (`FULL`, `PARTIAL`, `FAILED`) applied to trust updates and write-state decisions; failed quorum forces newly written memory toward `anergic`.  
**Limitation:** Legitimate new agents start with weak slow signal by design, so warm-up is required. This is intentional but introduces initial friction for benign onboarding.

### 4.4 Content-Addressed Storage
**Biological/mathematical analog:** Immutable content identity via Merkle-style addressing.  
**Attack it catches:** Storage-layer tampering, direct row mutation, and post-write content forgery attempts that bypass API-level validation logic.  
**Why existing systems miss it:** ID-addressed mutable records can be modified in place without cryptographic identity breakage unless extra controls exist.  
**Implementation:** Memory objects are assigned a deterministic hash over core write metadata (`content`, `agent_id`, `session_id`, `source_type`, `source_identifier`, `created_at`). Reads verify integrity and return validity metadata. Batch verification is supported for operational checks. Hash mismatch is treated as high-severity integrity failure.  
**Limitation:** This detects post-write tampering. A compromised write path can still inject malicious content before hashing unless the write path itself is independently hardened and signed.

### 4.5 Reconsolidation Write-Lock
**Biological/mathematical analog:** Reconsolidation window vulnerability during memory retrieval/rewrite.  
**Attack it catches:** Read-modify-write races where an attacker attempts concurrent metadata mutation while a memory is being consumed.  
**Why existing systems miss it:** Retrieval is usually assumed read-only and race-safe; most memory stacks do not model retrieval as a mutable risk window.  
**Implementation:** Read path acquires a Redis-backed lock, snapshots state, performs integrity/causal checks, and verifies consistency before release. Conflicting write/flag operations during this window are rejected (e.g., `409` conflict) and logged.  
**Limitation:** Lock duration is a tuning tradeoff. Short windows can miss slower races; long windows can hurt legitimate concurrency under high throughput.

### 4.6 Vector Clocks for Causal Ordering
**Biological/mathematical analog:** Distributed causal clocks (Lamport/vector-clock family).  
**Attack it catches:** Fabricated provenance chains, impossible temporal dependencies, orphaned context claims, and clock regressions.  
**Why existing systems miss it:** Recency/similarity ranking does not enforce causality; semantic plausibility is not structural validity.  
**Implementation:** Writes maintain per-agent logical clocks and inferred causal parents. Reads validate chain integrity (orphan checks, temporal paradox constraints, and consistency of causal metadata). Structural violations feed rule and flagging pathways (not only semantic anomaly pathways).  
**Limitation:** If agents write without reading context, causal chains remain shallow but valid. Structural confidence is then lower, though still machine-verifiable.

---

## SECTION 5: TRUST SCORE FORMULA

AgentMemory trust is multiplicative and explicit:

```text
trust_score = base_score
            * time_decay_factor          (exponential, source-type rates)
            * source_reliability_factor  (0.5 if flagged, 1.0 if not)
            * anomaly_penalty            (product of triggered penalties)
            * utility_multiplier         (SHY: 1.2 / 1.0 / 0.8 / 0.6)
            * reality_score_factor       (1.0 / 0.9 / 0.6 / 0.3)
            * quorum_multiplier          (1.0 / 0.7 / 0.3 by quorum status)
```

Time-decay rates by source type:

```text
tool_call:   lambda = 0.003  (slowest decay)
user_input:  lambda = 0.005
web_fetch:   lambda = 0.015
inter_agent: lambda = 0.020  (fastest decay)
```

SHY utility multiplier:

```text
retrieved + session success  -> 1.2
retrieved + unknown outcome  -> 1.0
never retrieved              -> 0.8
retrieved + session failed   -> 0.6
```

Reality score mapping:

```text
>= 0.9 (direct observation) -> 1.0
>= 0.7 (tool output)        -> 0.9
>= 0.5 (agent inference)    -> 0.6
< 0.5 (external claim)      -> 0.3
```

Quorum multiplier:

```text
FULL_QUORUM    -> 1.0
PARTIAL_QUORUM -> 0.7
FAILED_QUORUM  -> 0.3
```

The practical implication is that trust can degrade for multiple orthogonal reasons simultaneously: age, source, anomaly evidence, low utility, weak reality anchoring, and quorum failure. This avoids a single-point trust model where passing one check can overwhelm all others.

---

## SECTION 6: THE 13 DETECTION RULES

| ID | Name | Severity | What It Detects |
|---|---|---|---|
| RULE_001 | write_flood | CRITICAL | >50 memories in current session |
| RULE_002 | low_trust_chain | HIGH | 3+ flagged memories read before writing |
| RULE_003 | source_contradiction | MEDIUM | Content negates 3+ same-agent memories |
| RULE_004 | rapid_rewrite | HIGH | 5+ provenance events in 10 minutes |
| RULE_005 | unverified_high_stakes | MEDIUM | High-stakes keywords + `human_verified=false` |
| RULE_006 | inter_agent_without_session | LOW | `inter_agent` source with no session |
| RULE_007 | expired_safety_context | MEDIUM | `safety_context.context_expires_at` in past |
| RULE_008 | anonymous_agent | HIGH | `agent_id` not in registered agents |
| RULE_009 | bulk_same_content | HIGH | 5+ >90% identical memories same session |
| RULE_010 | trust_score_cliff | HIGH | `trust_score` dropped >0.4 in single cycle |
| RULE_011 | behavioral_drift | HIGH | Write pattern >2 sigma from registered baseline |
| RULE_012 | causal_orphan | HIGH | `context_hash` matches no known session + vector clock inconsistency path |
| RULE_013 | anergy_bypass_attempt | CRITICAL | Direct query for anergic memories |

Rules execute as background checks after writes. `MEDIUM` and above push notifications and are cached for rapid operational visibility. `CRITICAL` events can trigger immediate enforcement behavior; `RULE_013` is a direct block path returning `403`. In practice, `RULE_001` through `RULE_010` function as innate first-pass pattern defenses, while `RULE_011` through `RULE_013` add behavioral, structural, and adversarial query-layer protections.

---

## SECTION 7: WHAT THIS DOESN'T DO

AgentMemory is a research implementation, not a cryptographic final form of memory security. It does not use zero-knowledge proofs for provenance assertions, primarily because proof generation and verification overhead would materially impact real-time agent throughput in this architecture. It also does not implement Byzantine consensus over memory contribution, since that requires multiple independently operated replicas and fault assumptions outside this single-repo deployment model.

It does not provide on-chain or soulbound reputation guarantees. Reputation here is operational and local to the deployment, not globally portable or economically anchored. Contradiction detection is strongest when embeddings are available; without vectors, the system falls back to weaker symbolic cues and rule-based negation patterns. This is useful but not equivalent to high-quality semantic contradiction modeling.

Most importantly, AgentMemory is designed to detect, slow, and contain; it is not a formal proof that sufficiently patient adversaries can never accumulate reputation. Slow-signal trust requires time, not oracle-level truth access, so a strategic attacker can still attempt long-horizon adaptation. In production, the current guarantees should be paired with infrastructure hardening: Redis clustering, Postgres replication, and authenticated/signed write paths so that content-address integrity remains meaningful even when API-layer components are targeted.

---

## SECTION 8: COMPARISON TO EXISTING SYSTEMS

| Property | AgentMemory | MemGPT | Mem0 | HippoRAG |
|---|---|---|---|---|
| Memory states (anergy/quarantine) | ✅ | ❌ | ❌ | ❌ |
| Utility-based trust decay (SHY) | ✅ | ❌ | ❌ | ❌ |
| Causal ordering (vector clocks) | ✅ | ❌ | ❌ | ❌ |
| Behavioral identity fingerprinting | ✅ | ❌ | ❌ | ❌ |
| Multi-timescale trust signals | ✅ | ❌ | ❌ | ❌ |
| Content-addressed tamper detection | ✅ | ❌ | ❌ | ❌ |
| Reconsolidation vulnerability defense | ✅ | ❌ | ❌ | ❌ |
| Two-signal activation requirement | ✅ | ❌ | ❌ | ❌ |
| Full provenance audit trail | ✅ | partial | ❌ | ❌ |
| MCP tool interface | ✅ | ✅ | ✅ | ❌ |
| Production-ready (single repo) | demo | ✅ | ✅ | ✅ |

"Production-ready" here means battle-tested in production deployments. AgentMemory is a research implementation demonstrating these mechanisms, not a production-hardened library. The comparison above is primarily about security properties and detection/containment architecture, not ecosystem maturity.

---

## SECTION 9: RESEARCH GAPS THIS FILLS

The first gap is applying dendritic-cell style danger modeling directly to LLM agent memory integrity. Negative Selection and DCA families were built for earlier intrusion-detection contexts, but published implementations have not focused on agent-memory trust orchestration in modern multi-agent LLM stacks. AgentMemory operationalizes this with a dedicated `DendriticCellAgent` that continuously scores harm-oriented signals and feeds memory-state and trust decisions.

The second gap is causal memory ordering in practical RAG-style systems. Vector clocks are mature distributed-systems primitives, but current agent-memory products rely mostly on semantic retrieval and recency ranking, not causal correctness constraints. AgentMemory introduces vector-clock and causal-parent metadata at the memory layer, then validates that structure during reads. This adds a non-semantic defense plane that semantic prompt attacks cannot trivially mimic.

The third gap, mechanism-design incentives (for example VCG-style truthfulness pressure), is only partially addressed. AgentMemory's quorum model raises the cost of gaming by forcing multiple temporal channels to align, but it does not prove that honest contribution is the dominant strategy under rational adversaries. Economic incentive-compatible memory markets remain open research and are not claimed as solved here.

---

## SECTION 10: RUNNING THE SYSTEM

### Prerequisites

Docker and Docker Compose.

### Start

```bash
cd agent-memory
./run.sh
```

This builds and starts PostgreSQL (`pgvector`), Redis, API, and frontend, then runs the demo simulation.

### Run demo simulation

```bash
cd agent-memory
PYTHONPATH=. python backend/demo_simulation.py
```

### Run attack simulations

The current implementation invokes attack simulations at the end of `backend/demo_simulation.py`. Use:

```bash
cd agent-memory
PYTHONPATH=. python backend/demo_simulation.py
```

If an `--attacks-only` mode is introduced later, it can be used instead; at present the attack suite is integrated into the full run.

### Run tests

```bash
cd agent-memory
python smoke_test.py
```

### MCP integration

Set `AGENT_MEMORY_API_URL` in your agent environment. The MCP server surface is defined in `agent_memory_mcp/tools.py` (the tool list evolves with the API and currently exceeds the original 14-tool baseline).

### Environment variables

Core runtime variables used by this repository:

- `DATABASE_URL` (API database DSN)
- `REDIS_URL` (Redis DSN)
- `DEBUG`
- `TRUST_CACHE_TTL_SECONDS`
- `SESSION_WRITES_CACHE_TTL_SECONDS`
- `AGENT_MEMORY_API_URL` (MCP client target)
- `AGENT_MEMORY_API_PREFIX` (optional path prefix for mounted API)
- `MEMORY_API_URL` (used by `backend/demo_simulation.py`, defaults to `http://localhost:8000`)

Compose defaults are defined in `agent-memory/docker-compose.yml`; local development examples are in `agent-memory/.env.example`.

---

## SECTION 11: FUTURE WORK

A concrete next step is integrating mechanism-design incentives so that truthful memory contribution is not only monitored but economically favored. A VCG-style or related incentive layer would move the model from heuristic containment toward strategy-resistant participation. A second step is rigorous benchmarking against the MINJA-style attack corpus, including reproducible harnesses that measure not only injection success but downstream propagation and containment latency. That requires explicit replay pipelines and attack taxonomies aligned to Dong et al. (2025). A third step is stronger contradiction detection when embeddings are absent or degraded. Current symbolic fallback is intentionally conservative but weaker under adversarially crafted language. A practical upgrade path is hybrid contradiction scoring that combines lexical negation, causal constraints, and lightweight local embedding approximations so non-vector memories still receive meaningful structural contradiction scrutiny.

---

## Citation / Reference

- Matzinger, P. (1994). Tolerance, danger, and the extended family.  
- Tononi, G., & Cirelli, C. (2003). Sleep and synaptic homeostasis.  
- Nader, K., Schafe, G. E., & LeDoux, J. E. (2000). Fear memories require reconsolidation after retrieval.  
- Johnson, R. T., et al. (1993). Quorum sensing foundations in bacterial communication.  
- Lamport, L. (1978). Time, clocks, and the ordering of events in a distributed system.  
- Forrest, S., et al. (1994). Self-nonself discrimination in a computer (Negative Selection).  
- Aickelin, U., & Greensmith, J. (2007). The Dendritic Cell Algorithm.  
- Dong, et al. (2025). MINJA: Memory Injection Attacks in Multi-Agent LLM systems.  
- Zheng, et al. (2025). CP-WBFT (AAAI): consensus and robustness in distributed AI settings.
