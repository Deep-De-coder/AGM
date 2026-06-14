"""Defense ablation runner — mechanistic interpretability for the AGM defense stack.

Runs the full MINJA benchmark once as baseline, then once per (defense, attack)
combination with the named defense surgically disabled.  The resulting matrix
shows which defenses are independently necessary for each attack's containment.

Usage:
    python -m backend.tests.ablation_runner
    python -m backend.tests.ablation_runner --attack sleeper_cell
    python -m backend.tests.ablation_runner --defense dca
    python -m backend.tests.ablation_runner --output-json results.json --output-md report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.tests.benchmark_minja import AttackResult, MINJABenchmark, _ATTACKS
from backend.tests.ablation_toggles import DEFENSE_TOGGLES, DefenseToggle


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AblationCell:
    attack_name: str
    mechanism_id: str
    baseline_contained: bool
    contained_with_defense_disabled: bool

    @property
    def escaped_due_to_ablation(self) -> bool:
        """True when the baseline contained the attack but disabling this defense did not."""
        return self.baseline_contained and not self.contained_with_defense_disabled


@dataclass
class AblationResult:
    baseline: list[AttackResult]
    cells: list[AblationCell]
    toggles: list[DefenseToggle] = field(default_factory=list)

    def critical_defenses(self) -> dict[str, list[str]]:
        """Return {attack_name: [mechanism_id, ...]} for mechanisms whose removal lets the attack escape."""
        by_attack: dict[str, list[str]] = defaultdict(list)
        for cell in self.cells:
            if cell.escaped_due_to_ablation:
                by_attack[cell.attack_name].append(cell.mechanism_id)
        return dict(by_attack)

    def defense_contribution(self) -> dict[str, float]:
        """Return {mechanism_id: fraction_of_baseline-contained_attacks_that_escape_when_disabled}."""
        by_defense: dict[str, list[bool]] = defaultdict(list)
        for cell in self.cells:
            if cell.baseline_contained:
                by_defense[cell.mechanism_id].append(cell.escaped_due_to_ablation)
        return {
            mid: sum(escaped) / len(escaped) if escaped else 0.0
            for mid, escaped in by_defense.items()
        }

    def redundant_defenses(self) -> list[str]:
        """Return mechanism IDs with 0% contribution (disabling them never causes an escape)."""
        return [mid for mid, c in self.defense_contribution().items() if c == 0.0]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class AblationRunner:
    def __init__(self) -> None:
        self._benchmark = MINJABenchmark()

    async def run_baseline(self) -> list[AttackResult]:
        """Run all 7 attacks with the full defense stack enabled."""
        return await self._benchmark.run_all()

    async def _run_with_defense_disabled(
        self,
        toggle: DefenseToggle,
        attack_name: str,
    ) -> AttackResult:
        """Apply ablation patches for *toggle*, run *attack_name*, then restore."""
        with ExitStack() as stack:
            for target, replacement in toggle.patches:
                stack.enter_context(patch(target, replacement))
            return await self._benchmark.run_attack(attack_name)

    async def run_ablation(
        self,
        toggle: DefenseToggle,
        attack_name: str,
    ) -> AttackResult:
        """Public alias for :meth:`_run_with_defense_disabled`."""
        return await self._run_with_defense_disabled(toggle, attack_name)

    async def run_full_matrix(
        self,
        toggles: list[DefenseToggle] | None = None,
        attack_names: list[str] | None = None,
    ) -> AblationResult:
        """Run baseline + all (toggle, attack) combinations.

        Args:
            toggles: subset of DEFENSE_TOGGLES to test (default: all 8)
            attack_names: subset of _ATTACKS keys to run (default: all 7)
        """
        if toggles is None:
            toggles = DEFENSE_TOGGLES
        if attack_names is None:
            attack_names = list(_ATTACKS.keys())

        print("\n=== ABLATION: running baseline ===")
        baseline = await self.run_baseline()
        baseline_map = {r.attack_name: r.contained for r in baseline}

        cells: list[AblationCell] = []
        total = len(toggles) * len(attack_names)
        done = 0

        for toggle in toggles:
            print(f"\n=== ABLATION: disabling '{toggle.display_name}' ===")
            for attack_name in attack_names:
                done += 1
                print(f"  [{done}/{total}] {toggle.mechanism_id} × {attack_name}")
                try:
                    ablated = await self._run_with_defense_disabled(toggle, attack_name)
                except Exception as exc:
                    ablated = AttackResult(
                        attack_name=attack_name,
                        ttc_ms=None,
                        propagation_factor=0.0,
                        false_positive_rate=0.0,
                        rules_fired={},
                        contained=False,
                        verdict="ESCAPED",
                        evidence="",
                        notes=f"ablation error: {exc}",
                    )
                cells.append(
                    AblationCell(
                        attack_name=attack_name,
                        mechanism_id=toggle.mechanism_id,
                        baseline_contained=baseline_map.get(attack_name, False),
                        contained_with_defense_disabled=ablated.contained,
                    )
                )

        return AblationResult(baseline=baseline, cells=cells, toggles=toggles)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_ablation_report(result: AblationResult) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    attack_names = [r.attack_name for r in result.baseline]
    toggle_ids = [t.mechanism_id for t in (result.toggles or DEFENSE_TOGGLES)]
    # Preserve order even if toggles is empty
    if not toggle_ids:
        seen: list[str] = []
        for c in result.cells:
            if c.mechanism_id not in seen:
                seen.append(c.mechanism_id)
        toggle_ids = seen

    cell_map: dict[tuple[str, str], AblationCell] = {
        (c.mechanism_id, c.attack_name): c for c in result.cells
    }

    lines: list[str] = []
    lines.append("# Defense Ablation Analysis")
    lines.append(f"Generated: {now}")
    lines.append("")

    # ── baseline summary ───────────────────────────────────────────────────
    lines.append("## Baseline (full defense stack)")
    lines.append("")
    baseline_contained = sum(1 for r in result.baseline if r.contained)
    lines.append(f"Containment rate: **{baseline_contained}/{len(result.baseline)}** attacks")
    lines.append("")

    # ── ablation matrix ────────────────────────────────────────────────────
    lines.append("## Ablation Matrix")
    lines.append("")
    lines.append(
        "Legend: ✅ contained even without defense | ❌ escaped when defense disabled | "
        "— not tested"
    )
    lines.append("")

    # Build header
    short_names = {n: n.replace("_", " ").title()[:18] for n in attack_names}
    header_cells = ["Defense"] + [short_names[n] for n in attack_names]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")

    for mid in toggle_ids:
        row = [mid]
        for attack_name in attack_names:
            cell = cell_map.get((mid, attack_name))
            if cell is None:
                row.append("—")
            elif cell.escaped_due_to_ablation:
                row.append("❌")
            else:
                row.append("✅")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # ── critical defenses per attack ───────────────────────────────────────
    lines.append("## Critical Defense Dependencies")
    lines.append("")
    critical = result.critical_defenses()
    if critical:
        for attack_name in attack_names:
            deps = critical.get(attack_name, [])
            if deps:
                lines.append(f"**{attack_name}**: {', '.join(deps)}")
    else:
        lines.append("No defense was singularly critical (or no attacks were contained).")
    lines.append("")

    # ── defense contribution scores ────────────────────────────────────────
    lines.append("## Defense Contribution Scores")
    lines.append("")
    lines.append("*(Fraction of baseline-contained attacks that escape when this defense is removed)*")
    lines.append("")
    contrib = result.defense_contribution()
    lines.append("| Defense | Contribution |")
    lines.append("| ------- | ------------ |")
    for mid in toggle_ids:
        pct = contrib.get(mid, 0.0)
        bar = "█" * int(pct * 10)
        lines.append(f"| {mid} | {pct:.0%} {bar} |")
    lines.append("")

    # ── redundant defenses ─────────────────────────────────────────────────
    redundant = result.redundant_defenses()
    if redundant:
        lines.append("## Redundant Defenses")
        lines.append("")
        lines.append(
            "These defenses showed 0% individual contribution — either they are"
            " genuinely redundant with others, or no baseline-contained attack"
            " relies on them alone:"
        )
        lines.append("")
        for mid in redundant:
            lines.append(f"- {mid}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _async_main() -> None:
    parser = argparse.ArgumentParser(
        description="AGM Defense Ablation Testing Framework"
    )
    parser.add_argument(
        "--attack",
        metavar="NAME",
        help=f"Run ablation for one attack only. Choices: {', '.join(_ATTACKS)}",
    )
    parser.add_argument(
        "--defense",
        metavar="ID",
        help=f"Run ablation for one defense only. Choices: {', '.join(t.mechanism_id for t in DEFENSE_TOGGLES)}",
    )
    parser.add_argument(
        "--output-json",
        metavar="PATH",
        help="Save raw results to a JSON file.",
    )
    parser.add_argument(
        "--output-md",
        metavar="PATH",
        help="Save the Markdown report to a file.",
    )
    args = parser.parse_args()

    toggles: list[DefenseToggle] | None = None
    attack_names: list[str] | None = None

    if args.defense:
        ids = [t.mechanism_id for t in DEFENSE_TOGGLES]
        if args.defense not in ids:
            print(f"Unknown defense '{args.defense}'. Valid IDs: {ids}", file=sys.stderr)
            raise SystemExit(1)
        toggles = [t for t in DEFENSE_TOGGLES if t.mechanism_id == args.defense]

    if args.attack:
        if args.attack not in _ATTACKS:
            print(
                f"Unknown attack '{args.attack}'. Valid names: {list(_ATTACKS)}", file=sys.stderr
            )
            raise SystemExit(1)
        attack_names = [args.attack]

    runner = AblationRunner()
    result = await runner.run_full_matrix(toggles=toggles, attack_names=attack_names)

    report = generate_ablation_report(result)
    print("\n" + report)

    if args.output_md:
        Path(args.output_md).write_text(report, encoding="utf-8")
        print(f"Report saved to: {args.output_md}")

    if args.output_json:
        raw: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "baseline": [
                {
                    "attack_name": r.attack_name,
                    "contained": r.contained,
                    "verdict": r.verdict,
                    "rules_fired": r.rules_fired,
                    "propagation_factor": r.propagation_factor,
                    "false_positive_rate": r.false_positive_rate,
                }
                for r in result.baseline
            ],
            "cells": [
                {
                    "attack_name": c.attack_name,
                    "mechanism_id": c.mechanism_id,
                    "baseline_contained": c.baseline_contained,
                    "contained_with_defense_disabled": c.contained_with_defense_disabled,
                    "escaped_due_to_ablation": c.escaped_due_to_ablation,
                }
                for c in result.cells
            ],
            "critical_defenses": result.critical_defenses(),
            "defense_contribution": result.defense_contribution(),
            "redundant_defenses": result.redundant_defenses(),
        }
        Path(args.output_json).write_text(json.dumps(raw, indent=2), encoding="utf-8")
        print(f"JSON saved to: {args.output_json}")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
