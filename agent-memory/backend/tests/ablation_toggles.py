"""Defense mechanism ablation toggles for mechanistic interpretability testing.

Each DefenseToggle stores the ``unittest.mock.patch`` targets needed to surgically
disable one security mechanism.  Zero production code is modified; patches are
applied and torn down inside every ablation run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DefenseToggle:
    mechanism_id: str
    display_name: str
    description: str
    patches: list[tuple[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Replacement callables
# ---------------------------------------------------------------------------

async def _noop_population_scan(self: Any, *args: Any, **kwargs: Any) -> list[Any]:
    return []


async def _safe_get_agent_context(self: Any, agent_id: Any, db: Any) -> Any:
    from backend.dendritic_cell import DCASample

    return DCASample(
        agent_id=str(agent_id),
        danger_score=0.0,
        safe_score=1.0,
        net_context="MATURE_SAFE",
        triggered_dangers=[],
        triggered_safes=["ablation_noop"],
        sampled_at=datetime.now(timezone.utc),
    )


async def _noop_update_behavioral_hash(
    agent_id: Any,
    new_memory: Any,
    db: Any,
    session_context_type: str | None = None,
) -> tuple[str, float, None]:
    return ("0" * 64, 0.0, None)


async def _passthrough_quorum(
    agent_id: str,
    session_id: Any,
    db: Any,
    redis_client: Any,
) -> Any:
    from backend.lib.quorum_trust import QuorumScore

    return QuorumScore(
        agent_id=str(agent_id),
        session_id=str(session_id) if session_id else "",
        fast_signal=1.0,
        medium_signal=1.0,
        slow_signal=1.0,
        composite_score=1.0,
        quorum_status="FULL_QUORUM",
        memory_trust_multiplier=1.0,
        failing_signals=[],
        computed_at=datetime.now(timezone.utc),
    )


def _always_valid_content_hash(memory: Any) -> bool:
    return True


async def _always_valid_integrity(memory: Any, db: Any, redis: Any) -> dict[str, Any]:
    return {
        "valid": True,
        "stored_hash": getattr(memory, "content_hash", "") or "",
        "computed_hash": getattr(memory, "content_hash", "") or "",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


async def _always_acquire_lock(self: Any, *args: Any, **kwargs: Any) -> bool:
    return True


async def _always_verify_snapshot(self: Any, *args: Any, **kwargs: Any) -> bool:
    return True


async def _always_valid_causal_chain(memory: Any, db: Any) -> tuple[bool, str]:
    return (True, "ablation: causal chain validation disabled")


def _always_active_memory_state(payload: dict[str, Any]) -> str:
    return "active"


async def _noop_check_memory_rules(
    memory_id: str,
    db: Any,
    redis: Any,
) -> list[Any]:
    return []


async def _noop_collect_violations(
    db: Any,
    *,
    agent_id: Any = None,
) -> list[Any]:
    return []


# ---------------------------------------------------------------------------
# Toggle registry
# ---------------------------------------------------------------------------

DEFENSE_TOGGLES: list[DefenseToggle] = [
    DefenseToggle(
        mechanism_id="dca",
        display_name="Dendritic Cell Algorithm",
        description=(
            "Disable population-level danger signal computation and always return"
            " a safe agent context."
        ),
        patches=[
            (
                "backend.dendritic_cell.DendriticCellAgent.run_population_scan",
                _noop_population_scan,
            ),
            (
                "backend.dendritic_cell.DendriticCellAgent.get_agent_context",
                _safe_get_agent_context,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="behavioral_hash",
        display_name="Behavioral Hash",
        description="Disable rolling behavioral vector drift detection (always report zero drift).",
        patches=[
            (
                "backend.lib.behavioral_hash.update_agent_behavioral_hash",
                _noop_update_behavioral_hash,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="quorum",
        display_name="Quorum Trust",
        description="Disable corroboration requirement (always return FULL_QUORUM with 1.0 multiplier).",
        patches=[
            (
                "backend.lib.quorum_trust.compute_quorum_score",
                _passthrough_quorum,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="content_address",
        display_name="Content-Addressed Storage",
        description="Disable hash-based tamper detection (always report memory integrity valid).",
        patches=[
            (
                "backend.lib.content_address.verify_content_hash",
                _always_valid_content_hash,
            ),
            (
                "backend.lib.content_address.verify_memory_integrity",
                _always_valid_integrity,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="reconsolidation",
        display_name="Reconsolidation Guard",
        description="Disable write-lock and snapshot verification on memory mutation.",
        patches=[
            (
                "backend.lib.reconsolidation.ReconsolidationGuard.acquire_lock",
                _always_acquire_lock,
            ),
            (
                "backend.lib.reconsolidation.ReconsolidationGuard.verify_snapshot",
                _always_verify_snapshot,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="vector_clock",
        display_name="Vector Clocks",
        description="Disable causal ordering validation (always report chain valid).",
        patches=[
            (
                "backend.lib.vector_clock.validate_causal_chain",
                _always_valid_causal_chain,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="two_signal_anergy",
        display_name="Two-Signal Anergy",
        description="Disable anergy gating so all incoming memories start in active state.",
        patches=[
            (
                "backend.trust_engine.determine_initial_memory_state",
                _always_active_memory_state,
            ),
        ],
    ),
    DefenseToggle(
        mechanism_id="rules_engine",
        display_name="Rules Engine",
        description="Suppress all predefined rule checks (no violations persisted or returned).",
        patches=[
            (
                "backend.rules.checker.check_memory_rules",
                _noop_check_memory_rules,
            ),
            (
                "backend.rules.checker.collect_violations",
                _noop_collect_violations,
            ),
        ],
    ),
]
