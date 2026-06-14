"""Tests for the defense ablation testing framework."""

from __future__ import annotations

import pytest

from backend.tests.ablation_toggles import DEFENSE_TOGGLES, DefenseToggle
from backend.tests.ablation_runner import (
    AblationCell,
    AblationResult,
    AblationRunner,
    generate_ablation_report,
)
from backend.tests.benchmark_minja import AttackResult, MINJABenchmark, _ATTACKS


# ---------------------------------------------------------------------------
# TEST 1 — Toggle registry is complete
# ---------------------------------------------------------------------------


def test_toggle_registry_complete() -> None:
    assert len(DEFENSE_TOGGLES) == 8, (
        f"Expected 8 defense toggles, got {len(DEFENSE_TOGGLES)}"
    )

    ids = [t.mechanism_id for t in DEFENSE_TOGGLES]
    assert len(ids) == len(set(ids)), f"Duplicate mechanism_ids: {ids}"

    for toggle in DEFENSE_TOGGLES:
        assert toggle.patches, (
            f"Toggle '{toggle.mechanism_id}' has no patches defined"
        )
        assert toggle.display_name, (
            f"Toggle '{toggle.mechanism_id}' is missing display_name"
        )
        assert toggle.description, (
            f"Toggle '{toggle.mechanism_id}' is missing description"
        )


# ---------------------------------------------------------------------------
# TEST 2 — Single ablation run does not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_ablation_runs_without_crash() -> None:
    dca_toggle = next(t for t in DEFENSE_TOGGLES if t.mechanism_id == "dca")
    runner = AblationRunner()

    result = await runner.run_ablation(dca_toggle, "sleeper_cell")

    assert isinstance(result, AttackResult)
    assert result.attack_name == "sleeper_cell"
    assert result.verdict in ("CONTAINED", "ESCAPED", "PARTIAL")


# ---------------------------------------------------------------------------
# TEST 3 — Baseline matches independent benchmark run (count + attack names)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_matches_benchmark() -> None:
    runner = AblationRunner()
    baseline = await runner.run_baseline()

    benchmark = MINJABenchmark()
    bench_results = await benchmark.run_all()

    assert len(baseline) == len(bench_results), (
        f"Runner baseline has {len(baseline)} results; benchmark has {len(bench_results)}"
    )

    baseline_names = {r.attack_name for r in baseline}
    bench_names = {r.attack_name for r in bench_results}
    assert baseline_names == bench_names, (
        f"Attack name mismatch: {baseline_names} vs {bench_names}"
    )


# ---------------------------------------------------------------------------
# TEST 4 — AblationCell.escaped_due_to_ablation logic
# ---------------------------------------------------------------------------


def test_ablation_cell_logic() -> None:
    # baseline contained, defense disabled → escaped due to ablation
    cell_critical = AblationCell(
        attack_name="sleeper_cell",
        mechanism_id="dca",
        baseline_contained=True,
        contained_with_defense_disabled=False,
    )
    assert cell_critical.escaped_due_to_ablation is True

    # baseline contained, defense disabled still contained → not critical
    cell_redundant = AblationCell(
        attack_name="sleeper_cell",
        mechanism_id="quorum",
        baseline_contained=True,
        contained_with_defense_disabled=True,
    )
    assert cell_redundant.escaped_due_to_ablation is False

    # baseline did NOT contain attack → cannot "escape due to ablation"
    cell_uncontained = AblationCell(
        attack_name="echo_chamber",
        mechanism_id="rules_engine",
        baseline_contained=False,
        contained_with_defense_disabled=False,
    )
    assert cell_uncontained.escaped_due_to_ablation is False

    # baseline did not contain, defense disabled causes containment (unusual but possible)
    cell_odd = AblationCell(
        attack_name="anergy_escape",
        mechanism_id="two_signal_anergy",
        baseline_contained=False,
        contained_with_defense_disabled=True,
    )
    assert cell_odd.escaped_due_to_ablation is False


# ---------------------------------------------------------------------------
# TEST 5 — critical_defenses() and defense_contribution() compute correctly
# ---------------------------------------------------------------------------


def test_critical_defenses_computation() -> None:
    from backend.tests.benchmark_minja import AttackResult

    baseline = [
        AttackResult(
            attack_name="sleeper_cell",
            ttc_ms=1000.0,
            propagation_factor=0.0,
            false_positive_rate=0.0,
            rules_fired={},
            contained=True,
            verdict="CONTAINED",
        ),
        AttackResult(
            attack_name="echo_chamber",
            ttc_ms=None,
            propagation_factor=0.5,
            false_positive_rate=0.0,
            rules_fired={},
            contained=False,
            verdict="ESCAPED",
        ),
    ]

    cells = [
        # dca is critical for sleeper_cell (baseline contained, ablation escapes)
        AblationCell("sleeper_cell", "dca", True, False),
        # behavioral_hash is NOT critical for sleeper_cell (still contained without it)
        AblationCell("sleeper_cell", "behavioral_hash", True, True),
        # echo_chamber was not baseline-contained → neither cell can be "critical"
        AblationCell("echo_chamber", "dca", False, False),
        AblationCell("echo_chamber", "behavioral_hash", False, False),
    ]

    result = AblationResult(baseline=baseline, cells=cells)

    critical = result.critical_defenses()
    assert "sleeper_cell" in critical
    assert "dca" in critical["sleeper_cell"]
    assert "behavioral_hash" not in critical.get("sleeper_cell", [])
    assert "echo_chamber" not in critical

    contrib = result.defense_contribution()
    # dca escaped 1/1 baseline-contained attacks → 100%
    assert contrib["dca"] == pytest.approx(1.0)
    # behavioral_hash escaped 0/1 baseline-contained attacks → 0%
    assert contrib["behavioral_hash"] == pytest.approx(0.0)

    redundant = result.redundant_defenses()
    assert "behavioral_hash" in redundant
    assert "dca" not in redundant


# ---------------------------------------------------------------------------
# TEST 6 — Report generation does not crash and includes required headers
# ---------------------------------------------------------------------------


def test_report_generation_no_crash() -> None:
    from backend.tests.benchmark_minja import AttackResult

    baseline = [
        AttackResult(
            attack_name="sleeper_cell",
            ttc_ms=500.0,
            propagation_factor=0.0,
            false_positive_rate=0.0,
            rules_fired={"RULE_001": 1},
            contained=True,
            verdict="CONTAINED",
        ),
    ]

    cells = [
        AblationCell("sleeper_cell", "dca", True, False),
        AblationCell("sleeper_cell", "rules_engine", True, True),
    ]

    result = AblationResult(
        baseline=baseline,
        cells=cells,
        toggles=[
            t for t in DEFENSE_TOGGLES if t.mechanism_id in ("dca", "rules_engine")
        ],
    )

    report = generate_ablation_report(result)

    assert isinstance(report, str)
    assert len(report) > 0
    assert "# Defense Ablation Analysis" in report
    assert "## Ablation Matrix" in report
    assert "## Critical Defense Dependencies" in report
    assert "## Defense Contribution Scores" in report
    # dca escaped → should appear in critical dependencies section
    assert "dca" in report
