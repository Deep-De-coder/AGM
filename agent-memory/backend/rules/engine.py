"""Predefined rules and :class:`RuleViolation` dataclass."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

from backend.models import Agent, Memory, MemoryProvenanceLog, utcnow


@dataclass
class RuleViolation:
    memory_id: str | None
    agent_id: str
    rule_name: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    detected_at: datetime
    auto_flagged: bool


@dataclass
class AgentStats:
    """Aggregates passed into rule checks (populated by :mod:`backend.rules.checker`)."""

    session_write_count: int
    flagged_reads_in_session: int
    agent_registered: bool


@dataclass
class RuleContext:
    """Everything a rule needs to evaluate."""

    memory: Memory
    session_memories: list[Memory]
    same_agent_memories: list[Memory]
    agent_stats: AgentStats
    provenance_events: list[MemoryProvenanceLog]
    agent_db: Agent | None = None
    context_hash_matches_session: bool = False
    causal_chain_valid: bool | None = None
    causal_chain_reason: str | None = None


def _violation(
    ctx: RuleContext,
    rule_name: str,
    severity: str,
    description: str,
    *,
    auto_flagged: bool = False,
) -> RuleViolation:
    return RuleViolation(
        memory_id=str(ctx.memory.id),
        agent_id=str(ctx.memory.agent_id),
        rule_name=rule_name,
        severity=severity,
        description=description,
        detected_at=utcnow(),
        auto_flagged=auto_flagged,
    )


# --- RULE_001 write_flood -------------------------------------------------

WRITE_FLOOD_THRESHOLD = 50


def _check_write_flood(ctx: RuleContext) -> RuleViolation | None:
    if ctx.agent_stats.session_write_count > WRITE_FLOOD_THRESHOLD:
        return _violation(
            ctx,
            "RULE_001",
            "CRITICAL",
            "Write flood detected — possible memory poisoning attack or runaway agent loop.",
            auto_flagged=True,
        )
    return None


# --- RULE_002 low_trust_chain --------------------------------------------

FLAGGED_READS_THRESHOLD = 3


def _check_low_trust_chain(ctx: RuleContext) -> RuleViolation | None:
    if ctx.agent_stats.flagged_reads_in_session >= FLAGGED_READS_THRESHOLD:
        return _violation(
            ctx,
            "RULE_002",
            "HIGH",
            "Trust chain contamination — agent may have incorporated poisoned memories.",
            auto_flagged=True,
        )
    return None


# --- RULE_003 source_contradiction ----------------------------------------

_NEGATION_PATTERN = re.compile(
    r"\bnot\s+([a-zA-Z][a-zA-Z0-9_-]{1,})\b",
    re.IGNORECASE,
)


def _word_positive_in_text(text: str, word: str) -> bool:
    low = text.lower()
    w = word.lower()
    if w not in low:
        return False
    for m in re.finditer(r"\b" + re.escape(w) + r"\b", low):
        start = max(0, m.start() - 40)
        prefix = low[start : m.start()]
        if re.search(
            r"\b(?:not|never|no|isn't|isnt|don't|dont|doesn't|doesnt)\s+$",
            prefix,
        ):
            continue
        return True
    return False


def _check_source_contradiction(ctx: RuleContext) -> RuleViolation | None:
    peers = [
        m for m in ctx.same_agent_memories if m.id != ctx.memory.id and not m.is_deleted
    ]
    neg_terms = [m.group(1) for m in _NEGATION_PATTERN.finditer(ctx.memory.content)]
    for term in neg_terms:
        hits = sum(1 for p in peers if _word_positive_in_text(p.content, term))
        if hits >= 3:
            return _violation(
                ctx,
                "RULE_003",
                "MEDIUM",
                "Content contradicts established memories from the same agent.",
                auto_flagged=False,
            )
    return None


# --- RULE_004 rapid_rewrite ----------------------------------------------


def _events_in_10min_window(timestamps: list[datetime], min_count: int = 5) -> bool:
    if len(timestamps) < min_count:
        return False
    ts = sorted(timestamps)
    fixed: list[datetime] = []
    for t in ts:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        fixed.append(t)
    from collections import deque

    q: deque[datetime] = deque()
    for t in fixed:
        q.append(t)
        while q and (t - q[0]).total_seconds() > 600:
            q.popleft()
        if len(q) >= min_count:
            return True
    return False


def _check_rapid_rewrite(ctx: RuleContext) -> RuleViolation | None:
    times = [e.timestamp for e in ctx.provenance_events]
    if _events_in_10min_window(times, min_count=5):
        return _violation(
            ctx,
            "RULE_004",
            "HIGH",
            "Memory is being modified unusually rapidly — possible manipulation attempt.",
            auto_flagged=True,
        )
    return None


# --- RULE_005 unverified_high_stakes -------------------------------------

_HIGH_STAKES_KEYWORDS = (
    "delete",
    "execute",
    "transfer",
    "payment",
    "credentials",
    "password",
    "access token",
    "api key",
)


def _check_unverified_high_stakes(ctx: RuleContext) -> RuleViolation | None:
    sc = ctx.memory.safety_context or {}
    verified = sc.get("human_verified")
    if verified is True:
        return None
    low = ctx.memory.content.lower()
    if any(kw in low for kw in _HIGH_STAKES_KEYWORDS):
        return _violation(
            ctx,
            "RULE_005",
            "MEDIUM",
            "High-stakes action memory written without human verification.",
            auto_flagged=False,
        )
    return None


# --- RULE_006 inter_agent_without_session --------------------------------


def _check_inter_agent_without_session(ctx: RuleContext) -> RuleViolation | None:
    if ctx.memory.source_type == "inter_agent" and ctx.memory.session_id is None:
        return _violation(
            ctx,
            "RULE_006",
            "LOW",
            "Inter-agent memory written without session tracking — provenance incomplete.",
            auto_flagged=False,
        )
    return None


# --- RULE_011 behavioral_drift -------------------------------------------


def _check_behavioral_drift(ctx: RuleContext) -> RuleViolation | None:
    agent = ctx.agent_db
    if agent is None or agent.behavioral_baseline is None:
        return None
    bl = agent.behavioral_baseline
    mems = ctx.session_memories
    if not mems:
        return None
    n = len(mems)
    avg_len = sum(len(m.content) for m in mems) / float(n)
    std_c = float(bl.get("std_content_length", 50))
    base_c = float(bl.get("avg_content_length", 200))
    if abs(avg_len - base_c) > 2 * std_c:
        return _violation(
            ctx,
            "RULE_011",
            "HIGH",
            "Agent write pattern deviates >2σ from registered behavioral baseline — possible impersonation",
            auto_flagged=True,
        )
    std_w = float(bl.get("std_writes_per_session", 5))
    base_w = float(bl.get("avg_writes_per_session", 10))
    if abs(float(n) - base_w) > 2 * std_w:
        return _violation(
            ctx,
            "RULE_011",
            "HIGH",
            "Agent write pattern deviates >2σ from registered behavioral baseline — possible impersonation",
            auto_flagged=True,
        )
    return None


# --- RULE_012 causal_orphan ----------------------------------------------


def _check_causal_orphan(ctx: RuleContext) -> RuleViolation | None:
    if ctx.causal_chain_valid is False:
        return _violation(
            ctx,
            "RULE_012",
            "HIGH",
            ctx.causal_chain_reason
            or "Causal chain / vector clock validation failed",
            auto_flagged=True,
        )
    sc = ctx.memory.safety_context or {}
    ch = sc.get("context_hash")
    if ch is None:
        return _violation(
            ctx,
            "RULE_012",
            "HIGH",
            "Memory context_hash matches no known session state — possible fabricated or injected memory",
            auto_flagged=True,
        )
    if not ctx.context_hash_matches_session:
        return _violation(
            ctx,
            "RULE_012",
            "HIGH",
            "Memory context_hash matches no known session state — possible fabricated or injected memory",
            auto_flagged=True,
        )
    return None


# --- RULE_013 anergy_bypass_attempt (write-time: never fires) ------------


def _check_anergy_bypass_attempt(ctx: RuleContext) -> RuleViolation | None:
    return None


# --- RULE_007 expired_safety_context -------------------------------------


def _parse_expires_at(raw: object) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _check_expired_safety_context(ctx: RuleContext) -> RuleViolation | None:
    sc = ctx.memory.safety_context or {}
    raw = sc.get("context_expires_at")
    if raw is None:
        return None
    exp = _parse_expires_at(raw)
    if exp is None:
        return None
    now = datetime.now(timezone.utc)
    if exp < now:
        return _violation(
            ctx,
            "RULE_007",
            "MEDIUM",
            "Memory was written under a safety context that has since expired.",
            auto_flagged=False,
        )
    return None


# --- RULE_008 anonymous_agent --------------------------------------------


def _check_anonymous_agent(ctx: RuleContext) -> RuleViolation | None:
    if not ctx.agent_stats.agent_registered:
        return _violation(
            ctx,
            "RULE_008",
            "HIGH",
            "Memory written by unregistered agent identity — possible spoofing.",
            auto_flagged=True,
        )
    return None


# --- RULE_009 bulk_same_content ------------------------------------------

_SIMILARITY_THRESHOLD = 0.9
_BULK_COUNT = 5


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _check_bulk_same_content(ctx: RuleContext) -> RuleViolation | None:
    if ctx.memory.session_id is None:
        return None
    peers = [
        m for m in ctx.session_memories if m.id != ctx.memory.id and not m.is_deleted
    ]
    if not peers:
        return None
    content = ctx.memory.content
    similar = 0
    for p in peers:
        if _similarity(content, p.content) >= _SIMILARITY_THRESHOLD:
            similar += 1
    if similar >= _BULK_COUNT:
        return _violation(
            ctx,
            "RULE_009",
            "HIGH",
            "Duplicate content flood — possible injection attempt.",
            auto_flagged=True,
        )
    return None


# --- RULE_010 trust_score_cliff ------------------------------------------

_CLIFF_DROP = 0.4


def _check_trust_score_cliff(ctx: RuleContext) -> RuleViolation | None:
    for e in ctx.provenance_events:
        if e.event_type != "trust_updated":
            continue
        meta = e.event_metadata or {}
        prev = meta.get("previous_trust_score")
        new = meta.get("new_trust_score")
        if prev is None or new is None:
            continue
        try:
            p = float(prev)
            n = float(new)
        except (TypeError, ValueError):
            continue
        if p - n > _CLIFF_DROP:
            return _violation(
                ctx,
                "RULE_010",
                "HIGH",
                "Sudden trust collapse — multiple anomaly factors compounding.",
                auto_flagged=True,
            )
    return None


@dataclass
class Rule:
    name: str
    description: str
    severity: str
    check: Callable[[RuleContext], RuleViolation | None]


PREDEFINED_RULES: list[Rule] = [
    Rule(
        name="RULE_001",
        description="Session write flood (>50 writes).",
        severity="CRITICAL",
        check=_check_write_flood,
    ),
    Rule(
        name="RULE_002",
        description="Agent read 3+ flagged memories in session.",
        severity="HIGH",
        check=_check_low_trust_chain,
    ),
    Rule(
        name="RULE_003",
        description="Negated facts contradict other memories from same agent.",
        severity="MEDIUM",
        check=_check_source_contradiction,
    ),
    Rule(
        name="RULE_004",
        description="5+ provenance events within 10 minutes on same memory.",
        severity="HIGH",
        check=_check_rapid_rewrite,
    ),
    Rule(
        name="RULE_005",
        description="High-stakes keywords without human verification.",
        severity="MEDIUM",
        check=_check_unverified_high_stakes,
    ),
    Rule(
        name="RULE_006",
        description="inter_agent source without session_id.",
        severity="LOW",
        check=_check_inter_agent_without_session,
    ),
    Rule(
        name="RULE_007",
        description="safety_context.context_expires_at is in the past.",
        severity="MEDIUM",
        check=_check_expired_safety_context,
    ),
    Rule(
        name="RULE_008",
        description="Agent id not present in agents table.",
        severity="HIGH",
        check=_check_anonymous_agent,
    ),
    Rule(
        name="RULE_009",
        description="5+ near-duplicate memories in same session.",
        severity="HIGH",
        check=_check_bulk_same_content,
    ),
    Rule(
        name="RULE_010",
        description="Trust dropped >0.4 in one trust_updated event.",
        severity="HIGH",
        check=_check_trust_score_cliff,
    ),
    Rule(
        name="RULE_011",
        description="Write pattern deviates from behavioral baseline (>2σ).",
        severity="HIGH",
        check=_check_behavioral_drift,
    ),
    Rule(
        name="RULE_012",
        description="safety_context.context_hash missing or unknown session.",
        severity="HIGH",
        check=_check_causal_orphan,
    ),
    Rule(
        name="RULE_013",
        description="Direct query for anergic memories (checked at query time).",
        severity="CRITICAL",
        check=_check_anergy_bypass_attempt,
    ),
]
