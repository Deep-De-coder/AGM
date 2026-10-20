"""
Pytest wrapper for the MINJA Resilience Benchmark.

This is a regression gate, not the goal. It fails if an attack that the defence
stack currently contains stops being contained, or if mean FPR reaches 0.10.
The target is 7/7; the measured baseline and the open gaps are documented in
docs/BENCHMARK.md and the README ("Attack Simulations").
"""

from __future__ import annotations


import pytest

from backend.tests.benchmark_minja import AttackResult, MINJABenchmark, _ATTACKS

# Attacks the stack is measured to contain today. When a fix makes another attack
# contained, add it here (and update docs/BENCHMARK.md) so it cannot regress.
EXPECTED_CONTAINED = {"echo_chamber", "anergy_escape"}

@pytest.fixture(autouse=True)
def _disable_trust_background_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the periodic trust loop from interfering with assertions."""
    monkeypatch.setattr(
        "backend.main.start_trust_background_task",
        lambda *args, **kwargs: None,
    )

    async def _noop_stop() -> None:
        return None

    monkeypatch.setattr("backend.main.stop_trust_background_task", _noop_stop)


@pytest.mark.asyncio
async def test_benchmark_full_suite() -> None:
    """Run all 7 attacks; no contained attack may regress, mean FPR < 0.10."""
    bench = MINJABenchmark()
    results: list[AttackResult] = await bench.run_all()

    assert len(results) == 7, f"Expected 7 results, got {len(results)}"

    containment_rate = sum(1 for r in results if r.contained)
    mean_fpr = sum(r.false_positive_rate for r in results) / len(results)

    # Print a brief summary for CI logs
    print(f"\nContainment: {containment_rate}/7")
    print(f"Mean FPR:    {mean_fpr:.4f}")
    for r in results:
        print(
            f"  {r.attack_name:<28} verdict={r.verdict:<10} "
            f"fpr={r.false_positive_rate:.4f}  rules={list(r.rules_fired)}"
        )

    contained = {r.attack_name for r in results if r.contained}
    regressed = EXPECTED_CONTAINED - contained
    assert not regressed, (
        f"No longer contained: {sorted(regressed)} "
        f"(containment {containment_rate}/7). "
        "Run the standalone benchmark for full details."
    )
    newly = contained - EXPECTED_CONTAINED
    if newly:
        print(f"Newly contained (add to EXPECTED_CONTAINED): {sorted(newly)}")
    assert mean_fpr < 0.10, (
        f"Mean FPR {mean_fpr:.4f} exceeds CI threshold of 0.10. "
        "Check if defensive rules are over-triggering on legitimate writes."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("attack_name", list(_ATTACKS))
async def test_individual_attack_no_crash(attack_name: str) -> None:
    """Each attack must complete without raising an unhandled exception."""
    bench = MINJABenchmark()
    result = await bench.run_attack(attack_name)
    # As long as we get a structured result back, the harness is working.
    assert isinstance(result, AttackResult)
    assert result.attack_name == attack_name
    assert result.verdict in ("CONTAINED", "ESCAPED", "PARTIAL")
    assert 0.0 <= result.propagation_factor <= 1.0
    assert 0.0 <= result.false_positive_rate <= 1.0
