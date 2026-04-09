# Rules engine

The rules package evaluates **predefined policies** on memory rows. After each `POST /memories` write, `check_memory_rules()` runs in a background task, persists hits to the `rule_violations` table, caches summaries in Redis, and enqueues **MEDIUM+** alerts via `notifications`.

## Predefined rules

| ID | Name (internal) | Severity | What it detects | Rationale |
|----|-----------------|----------|-----------------|-----------|
| RULE_001 | write_flood | CRITICAL | More than **50** writes in the current agent **session** (Redis `writes:*`). | Indicates a possible poisoning or runaway loop; highest impact. |
| RULE_002 | low_trust_chain | HIGH | **≥3** flagged memories read in-session (Redis `flagged_reads:*`). | Agent may have absorbed untrusted content. |
| RULE_003 | source_contradiction | MEDIUM | Negated `not X` patterns where **X** appears positively in **≥3** other memories from the **same agent**. | Contradicts prior “facts”; erodes consistency. |
| RULE_004 | rapid_rewrite | HIGH | **≥5** provenance events on the **same memory** within **10 minutes**. | Suggests rapid manipulation or churn. |
| RULE_005 | unverified_high_stakes | MEDIUM | `safety_context.human_verified` is not `true` and content matches high-stakes keywords (delete, payment, credentials, etc.). | Sensitive actions should be human-verified. |
| RULE_006 | inter_agent_without_session | LOW | `source_type == "inter_agent"` but `session_id` is null. | Provenance gap; audit trail weaker. |
| RULE_007 | expired_safety_context | MEDIUM | `safety_context.context_expires_at` parses to a **past** time. | Policy window expired. |
| RULE_008 | anonymous_agent | HIGH | `agent_id` not found in `agents` (e.g. DB integrity edge cases). | Possible spoofed identity. |
| RULE_009 | bulk_same_content | HIGH | **≥5** memories in the **same session** with **>90%** text similarity to the current (`difflib.SequenceMatcher`). | Duplicate flood / injection. |
| RULE_010 | trust_score_cliff | HIGH | A `trust_updated` provenance event shows **previous − new > 0.4**. | Sudden trust collapse. |

## Adding a custom rule

1. Add a `def _check_my_rule(ctx: RuleContext) -> RuleViolation | None` in `engine.py` (or a submodule).
2. Append a `Rule(name="RULE_011", description="...", severity="MEDIUM", check=_check_my_rule)` to `PREDEFINED_RULES`.
3. Keep checks **pure** where possible: use `RuleContext` only (memory, session peers, same-agent peers, stats, provenance).
4. If the rule needs new data, extend `RuleContext` and populate it in `checker.check_memory_rules` / `collect_violations`.

## Persistence and notifications

- **Persisted** rows: `backend.models.RuleViolation` → table `rule_violations` (see Alembic `003_rule_violations`).
- **Redis** list per memory: `rule_violations:memory:{memory_id}` (last 100 entries).
- **Notifications** (MEDIUM+): `backend.notifications.push_notification` → Redis list `notifications` + `asyncio.Queue` for in-process consumers.
