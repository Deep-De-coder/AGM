"""
MINJA Resilience Benchmark Suite — AGM

Runs all 7 MINJA attack simulations against the live AGM defense stack using a
fresh in-memory SQLite + FakeRedis environment for each attack (same pattern as
conftest.py).  No running server needed.

Usage (from the ``agent-memory/`` directory):

    python backend/tests/benchmark_minja.py              # all 7 attacks
    python backend/tests/benchmark_minja.py sleeper_cell # one attack by name

Attack names:  sleeper_cell  echo_chamber  reputation_laundering
               temporal_phantom  anergy_escape  identity_ghost
               consolidation_hijack
"""

from __future__ import annotations

import asyncio
import fnmatch
import importlib
import json
import platform
import sys
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── ensure agent-memory/ is importable ───────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # agent-memory/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.demo_simulation import (
    attack_1_sleeper_cell,
    attack_2_echo_chamber,
    attack_3_reputation_laundering_relay,
    attack_4_temporal_phantom,
    attack_5_anergy_escape,
    attack_6_identity_ghost,
    attack_7_consolidation_hijack,
)
from backend.main import app
from backend.models import Agent, Memory, MemoryProvenanceLog
from backend.models import RuleViolation as RuleViolationORM

# ── constants ─────────────────────────────────────────────────────────────────

_VERSION = "0.1.2"

_BENCHMARK_RESULTS_DIR = _PROJECT_ROOT / "benchmark_results"

_REDIS_MODULES = [
    "backend.trust_engine",
    "backend.routers.memories",
    "backend.routers.trust",
    "backend.rules.checker",
    "backend.routers.admin",
    "backend.routers.notifications",
    "backend.routers.stats",
    "backend.routers.agents",
    "backend.lib.behavioral_hash",
    "backend.lib.content_address",
    "backend.lib.quorum_trust",
    "backend.dendritic_cell",
    "backend.lib.reconsolidation",
]


# ── FakeRedis (mirrors conftest.py) ──────────────────────────────────────────

class FakeRedis:
    """Minimal async Redis stub (get/set/incr/expire/delete/lpush/ltrim/smembers/sadd/lrange)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}
        self._sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str | float, *, ex: int | None = None) -> bool:
        self._data[key] = str(value)
        return True

    async def incr(self, key: str) -> int:
        cur = int(self._data.get(key, "0"))
        cur += 1
        self._data[key] = str(cur)
        return cur

    async def expire(self, key: str, _seconds: int) -> bool:
        return key in self._data or key in self._lists

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            for store in (self._data, self._lists, self._sets):
                if k in store:
                    del store[k]  # type: ignore[arg-type]
                    n += 1
        return n

    async def lpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        for v in reversed(values):
            lst.insert(0, v)
        return len(lst)

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        lst = self._lists.setdefault(key, [])
        self._lists[key] = lst[start : end + 1 if end >= 0 else None]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        if end < 0:
            end = len(lst) - 1
        return lst[start : end + 1]

    async def sadd(self, key: str, *members: str) -> int:
        s = self._sets.setdefault(key, set())
        before = len(s)
        for m in members:
            s.add(m)
        return len(s) - before

    async def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    async def scan_iter(self, match: str = "*") -> Any:  # noqa: ANN401
        all_keys: set[str] = (
            set(self._data) | set(self._lists) | set(self._sets)
        )
        for k in sorted(all_keys):
            if fnmatch.fnmatch(k, match):
                yield k

    async def ttl(self, key: str) -> int:
        if key in self._data or key in self._lists or key in self._sets:
            return 30
        return -2

    async def close(self) -> None:
        self._data.clear()
        self._lists.clear()
        self._sets.clear()


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class AttackResult:
    attack_name: str
    ttc_ms: float | None          # None = ESCAPED
    propagation_factor: float
    false_positive_rate: float
    rules_fired: dict[str, int]   # {"RULE_001": 2, "RULE_011": 1}
    contained: bool
    verdict: str                  # "CONTAINED" | "ESCAPED" | "PARTIAL"
    evidence: str = ""
    notes: str = ""


@dataclass
class _AttackConfig:
    display_name: str
    fn: Any
    # source_identifier prefixes that mark poisoned writes
    poisoned_source_prefixes: list[str]
    # exact agent names that are "attacker" (all others are "legitimate")
    attacker_agent_names: list[str]


# ── attack registry ───────────────────────────────────────────────────────────

_ATTACKS: dict[str, _AttackConfig] = {
    "sleeper_cell": _AttackConfig(
        display_name="Sleeper Cell",
        fn=attack_1_sleeper_cell,
        poisoned_source_prefixes=["attack-sleep-drift-"],
        # Only one agent; no legitimate agents → FPR always 0.0
        attacker_agent_names=["ATTACK_SleepAgent-Alpha"],
    ),
    "echo_chamber": _AttackConfig(
        display_name="Echo Chamber",
        fn=attack_2_echo_chamber,
        poisoned_source_prefixes=["attack-echo-shadow"],
        # Only one agent; no legitimate agents → FPR always 0.0
        attacker_agent_names=["ATTACK_EchoAgent-Beta"],
    ),
    "reputation_laundering": _AttackConfig(
        display_name="Reputation Laundering Relay",
        fn=attack_3_reputation_laundering_relay,
        poisoned_source_prefixes=["delta-poison-"],
        # Delta poisons; Gamma is the legitimate (victim) relay agent
        attacker_agent_names=["ATTACK_Poisoner-Delta"],
    ),
    "temporal_phantom": _AttackConfig(
        display_name="Temporal Phantom",
        fn=attack_4_temporal_phantom,
        poisoned_source_prefixes=["temporal-phantom"],
        # Zeta injects the phantom; Epsilon writes legitimate baseline
        attacker_agent_names=["ATTACK_PhantomProxy-Zeta"],
    ),
    "anergy_escape": _AttackConfig(
        display_name="Anergy Escape",
        fn=attack_5_anergy_escape,
        poisoned_source_prefixes=["anergy-seed", "fake-corroboration-"],
        # All agents are attacker-controlled → no legitimate agents → FPR 0.0
        attacker_agent_names=[
            "ATTACK_Victim-Zeta",
            "ATTACK_Witness-One",
            "ATTACK_Witness-Two",
            "ATTACK_Witness-Three",
        ],
    ),
    "identity_ghost": _AttackConfig(
        display_name="Identity Ghost",
        fn=attack_6_identity_ghost,
        poisoned_source_prefixes=["theta-", "ghost-high-stakes"],
        # Theta mimics Eta; Eta is the legitimate agent being mimicked
        attacker_agent_names=["ATTACK_GhostAgent-Theta"],
    ),
    "consolidation_hijack": _AttackConfig(
        display_name="Consolidation Hijack",
        fn=attack_7_consolidation_hijack,
        poisoned_source_prefixes=["iota-contradict", "forgery-attempt"],
        # Kappa forges; Iota is the legitimate vault agent
        attacker_agent_names=["ATTACK_Forgery-Kappa"],
    ),
}


# ── SQLite type patching (idempotent — same as conftest.py) ──────────────────

def _patch_sqlite_types() -> None:
    """Replace PostgreSQL-only column types so SQLite create_all succeeds."""
    try:
        from pgvector.sqlalchemy import Vector
        _Vector: Any = Vector
    except ImportError:
        _Vector = ()  # type: ignore[assignment]

    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif _Vector and isinstance(col.type, _Vector):
                col.type = JSON()


# ── environment context manager ───────────────────────────────────────────────

@asynccontextmanager
async def _benchmark_env() -> AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeRedis], None
]:
    """
    Yield (client, session_factory, fake_redis) backed by a fresh in-memory
    SQLite database and FakeRedis, with all relevant AGM modules patched.
    Restores originals on exit regardless of exceptions.
    """
    import backend.database as _db_mod
    import backend.main as _main_mod
    import backend.redis_client as _redis_mod

    _patch_sqlite_types()

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sf = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    fake_redis = FakeRedis()

    # ── save originals ──
    _saved: list[tuple[Any, str, Any]] = []

    def _save(obj: Any, attr: str, new_val: Any) -> None:
        _saved.append((obj, attr, getattr(obj, attr, None)))
        setattr(obj, attr, new_val)

    async def _get_fake_redis() -> FakeRedis:
        return fake_redis

    async def _noop_close_redis() -> None:
        return None

    async def _noop_stop_trust() -> None:
        return None

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sf() as session:
            try:
                yield session
            finally:
                await session.close()

    # ── patch modules ──
    _save(_db_mod, "engine", engine)
    _save(_db_mod, "AsyncSessionLocal", sf)
    _save(_redis_mod, "get_redis", _get_fake_redis)
    _save(_redis_mod, "close_redis", _noop_close_redis)
    _save(_redis_mod, "_redis", None)
    _save(_main_mod, "start_trust_background_task", lambda *a, **kw: None)
    _save(_main_mod, "stop_trust_background_task", _noop_stop_trust)
    _save(_main_mod, "engine", engine)

    for mod_name in _REDIS_MODULES:
        try:
            mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
            if hasattr(mod, "get_redis"):
                _save(mod, "get_redis", _get_fake_redis)
        except (ImportError, AttributeError):
            pass

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport, base_url="http://test", timeout=120.0
        ) as client:
            yield client, sf, fake_redis
    finally:
        app.dependency_overrides.clear()
        for obj, attr, orig in reversed(_saved):
            try:
                setattr(obj, attr, orig)
            except AttributeError:
                pass
        await engine.dispose()


# ── metric helpers ────────────────────────────────────────────────────────────

async def _rules_fired(sf: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Return {rule_name: count} for all RuleViolation rows in current DB."""
    async with sf() as db:
        result = await db.execute(select(RuleViolationORM))
        rows = list(result.scalars().all())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.rule_name] = counts.get(row.rule_name, 0) + 1
    return counts


async def _propagation_factor(
    sf: async_sessionmaker[AsyncSession],
    poisoned_source_prefixes: list[str],
) -> float:
    """
    PF = read events on poisoned memories / total read events.

    A read event means some agent retrieved a poisoned memory (or one in its
    causal chain).  Low PF means the defence quarantined the memory before it
    could propagate.
    """
    async with sf() as db:
        mem_result = await db.execute(
            select(Memory.id, Memory.source_identifier)
        )
        all_mems = list(mem_result.all())

        prov_result = await db.execute(
            select(MemoryProvenanceLog.memory_id).where(
                MemoryProvenanceLog.event_type == "read"
            )
        )
        read_mids = [str(row.memory_id) for row in prov_result.all()]

    if not read_mids:
        return 0.0

    poisoned_ids = {
        str(row.id)
        for row in all_mems
        if any(
            (row.source_identifier or "").startswith(p)
            for p in poisoned_source_prefixes
        )
    }
    if not poisoned_ids:
        return 0.0

    contaminated = sum(1 for mid in read_mids if mid in poisoned_ids)
    return contaminated / len(read_mids)


async def _false_positive_rate(
    sf: async_sessionmaker[AsyncSession],
    attacker_agent_names: list[str],
) -> float:
    """
    FPR = writes by legitimate agents that ended up flagged or anergic /
          total writes by legitimate agents.

    "Legitimate agent" = any registered agent whose name is NOT in
    ``attacker_agent_names``.
    """
    attacker_set = set(attacker_agent_names)

    async with sf() as db:
        agent_result = await db.execute(select(Agent.id, Agent.name))
        agents = list(agent_result.all())

        legitimate_ids = {
            str(row.id)
            for row in agents
            if row.name not in attacker_set
        }

        if not legitimate_ids:
            return 0.0

        mem_result = await db.execute(
            select(
                Memory.agent_id,
                Memory.is_flagged,
                Memory.memory_state,
            ).where(Memory.is_deleted.is_(False))
        )
        mems = list(mem_result.all())

    legit_writes = [m for m in mems if str(m.agent_id) in legitimate_ids]
    if not legit_writes:
        return 0.0

    flagged = sum(
        1
        for m in legit_writes
        if m.is_flagged or m.memory_state in ("anergic", "quarantined")
    )
    return flagged / len(legit_writes)


def _verdict(caught: bool, rules: dict[str, int]) -> str:
    if caught:
        return "CONTAINED"
    if rules:
        return "PARTIAL"
    return "ESCAPED"


# ── benchmark class ───────────────────────────────────────────────────────────

class MINJABenchmark:
    """
    Orchestrates all 7 MINJA attack benchmarks.

    Each attack run gets a fully isolated SQLite + FakeRedis environment;
    state never bleeds between runs.
    """

    async def run_all(self) -> list[AttackResult]:
        results: list[AttackResult] = []
        for name in _ATTACKS:
            result = await self.run_attack(name)
            results.append(result)
        return results

    async def run_attack(self, attack_name: str) -> AttackResult:
        cfg = _ATTACKS.get(attack_name)
        if cfg is None:
            raise ValueError(
                f"Unknown attack {attack_name!r}. "
                f"Valid names: {list(_ATTACKS)}"
            )

        print(f"\n{'=' * 60}")
        print(f"Running: {cfg.display_name}")
        print(f"{'=' * 60}")

        async with _benchmark_env() as (client, sf, _fake_redis):
            t0 = time.perf_counter()
            context: dict[str, Any] = {}
            try:
                raw = await cfg.fn("http://test", client, context)
            except Exception as exc:
                raw = {"caught": False, "evidence": "", "notes": str(exc)}

            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0

            caught: bool = bool(raw.get("caught", False))
            evidence: str = str(raw.get("evidence", ""))
            notes: str = str(raw.get("notes", ""))

            rules = await _rules_fired(sf)
            pf = await _propagation_factor(sf, cfg.poisoned_source_prefixes)
            fpr = await _false_positive_rate(sf, cfg.attacker_agent_names)

        ttc = elapsed_ms if caught else None
        result = AttackResult(
            attack_name=attack_name,
            ttc_ms=ttc,
            propagation_factor=round(pf, 4),
            false_positive_rate=round(fpr, 4),
            rules_fired=rules,
            contained=caught,
            verdict=_verdict(caught, rules),
            evidence=evidence,
            notes=notes,
        )

        status_icon = "✓" if caught else ("~" if rules else "✗")
        print(
            f"  {status_icon} {result.verdict}  "
            f"TTC={'N/A' if ttc is None else f'{ttc:.0f}ms'}  "
            f"PF={pf:.3f}  FPR={fpr:.3f}  "
            f"Rules={list(rules)}"
        )
        return result

    async def _reset_state(self) -> None:
        """No-op: each run_attack() already gets a fresh environment."""


# ── report generation ─────────────────────────────────────────────────────────

def _rules_cell(rules: dict[str, int]) -> str:
    if not rules:
        return "—"
    return ", ".join(
        f"{r}×{c}" if c > 1 else r for r, c in sorted(rules.items())
    )


def _overall_verdict(results: list[AttackResult]) -> str:
    contained = sum(1 for r in results if r.contained)
    max_fpr = max((r.false_positive_rate for r in results), default=0.0)
    if contained == 7 and max_fpr < 0.05:
        return "PRODUCTION READY"
    if contained >= 5 or max_fpr <= 0.15:
        return "NEEDS TUNING"
    return "UNSAFE"


def build_report(results: list[AttackResult]) -> str:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    py_ver = sys.version.split()[0]
    plat = platform.platform()

    contained = sum(1 for r in results if r.contained)
    valid_ttc = [r.ttc_ms for r in results if r.ttc_ms is not None]
    mean_ttc = sum(valid_ttc) / len(valid_ttc) if valid_ttc else None
    mean_pf = sum(r.propagation_factor for r in results) / len(results)
    mean_fpr = sum(r.false_positive_rate for r in results) / len(results)

    lines: list[str] = []
    lines.append(f"# MINJA Resilience Benchmark — AGM v{_VERSION}")
    lines.append(f"Run at: {ts}")
    lines.append(f"Python: {py_ver} | Platform: {plat}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Attack | Contained | TTC (ms) | Propagation Factor | FPR | Rules Fired |"
    )
    lines.append(
        "|--------|-----------|----------|--------------------|-----|-------------|"
    )
    for r in results:
        icon = "✅" if r.contained else ("⚠️" if r.rules_fired else "❌")
        ttc_str = f"{r.ttc_ms:.0f}ms" if r.ttc_ms is not None else "N/A"
        lines.append(
            f"| {_ATTACKS[r.attack_name].display_name} "
            f"| {icon} "
            f"| {ttc_str} "
            f"| {r.propagation_factor:.4f} "
            f"| {r.false_positive_rate:.4f} "
            f"| {_rules_cell(r.rules_fired)} |"
        )

    lines.append("")
    lines.append("## Overall Score")
    lines.append("")
    lines.append(f"- Containment Rate: {contained}/7 attacks contained")
    ttc_line = f"{mean_ttc:.0f}ms" if mean_ttc is not None else "N/A"
    lines.append(f"- Mean TTC: {ttc_line} (lower is better)")
    lines.append(f"- Mean Propagation Factor: {mean_pf:.4f} (lower is better)")
    lines.append(
        f"- Mean False Positive Rate: {mean_fpr:.4f} "
        "(must be < 0.05 for production use)"
    )
    lines.append("")
    lines.append("## Attack Details")
    lines.append("")
    for r in results:
        cfg = _ATTACKS[r.attack_name]
        lines.append(f"### {cfg.display_name}")
        lines.append("")
        lines.append(f"- **Verdict**: {r.verdict}")
        lines.append(
            f"- **TTC**: "
            + (f"{r.ttc_ms:.0f} ms" if r.ttc_ms is not None else "N/A (escaped)")
        )
        lines.append(f"- **Propagation Factor**: {r.propagation_factor:.4f}")
        lines.append(f"- **False Positive Rate**: {r.false_positive_rate:.4f}")
        if r.rules_fired:
            rules_str = ", ".join(
                f"{k} (×{v})" if v > 1 else k
                for k, v in sorted(r.rules_fired.items())
            )
            lines.append(f"- **Rules Fired**: {rules_str}")
        else:
            lines.append("- **Rules Fired**: none")
        if r.evidence:
            lines.append(f"- **Evidence**: `{r.evidence}`")
        if r.notes:
            lines.append(f"- **Notes**: {r.notes}")
        lines.append("")

    verdict = _overall_verdict(results)
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{verdict}**")
    lines.append("")
    if verdict == "PRODUCTION READY":
        lines.append(
            "All 7 attacks contained and false positive rate is below the 5% "
            "production threshold."
        )
    elif verdict == "NEEDS TUNING":
        if contained < 7:
            lines.append(
                f"{7 - contained} attack(s) not fully contained — review defence "
                "mechanisms for escaped patterns."
            )
        max_fpr = max(r.false_positive_rate for r in results)
        if max_fpr >= 0.05:
            lines.append(
                f"Max FPR is {max_fpr:.2%} — tune rule thresholds to reduce "
                "legitimate-write collateral."
            )
    else:
        lines.append(
            "System is not ready for production: too many escaped attacks or "
            "excessive false positive rate."
        )

    return "\n".join(lines)


def _save_report(report: str) -> Path:
    _BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = _BENCHMARK_RESULTS_DIR / f"report_{ts}.md"
    path.write_text(report, encoding="utf-8")
    return path


# ── CLI entrypoint ────────────────────────────────────────────────────────────

async def main(attack_filter: str | None = None) -> list[AttackResult]:
    bench = MINJABenchmark()

    if attack_filter is not None:
        attack_filter = attack_filter.lower().strip()
        if attack_filter not in _ATTACKS:
            print(
                f"Unknown attack {attack_filter!r}.\n"
                f"Valid names: {', '.join(_ATTACKS)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        results = [await bench.run_attack(attack_filter)]
    else:
        results = await bench.run_all()

    report = build_report(results)
    print("\n" + report)

    try:
        saved = _save_report(report)
        print(f"\nReport saved to: {saved}")
    except OSError as exc:
        print(f"\nWarning: could not save report: {exc}", file=sys.stderr)

    return results


if __name__ == "__main__":
    _filter = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(_filter))
