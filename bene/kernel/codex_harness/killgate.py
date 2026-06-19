"""Hash-locked kill-gate for codex-harness evolution — SECH Contract G (bene-core).

Identical falsifiable-probe machinery to the battle kill-gate, but self-contained so
``codex_harness`` carries no dependency on ``bene.kernel.battle``. Gates are frozen at
import time; editing them and running the probe raises ``LockTamperError``.

Three gates (all required for ACCEPT):
  win_rate_uplift     — evolved must beat seed by >=10pp on held-out (relative)
  battles_played_gt0  — anti-vacuous: at least one real battle was played
  gens_completed_gt0  — anti-vacuous: at least one evolution generation ran

The gate spec is sha256-locked at registration; a harness identical to seed shows 0
win_rate uplift -> gate kills -> the probe IS admissible (falsifiable).
"""

from __future__ import annotations

import sqlite3

from bene.kernel.codex_harness.genome import CodexFitness
from bene.kernel.engrams import EngramStore
from bene.kernel.eval.gates import Gate
from bene.kernel.eval.probe import Probe
from bene.kernel.schema_v2 import ensure_v2

# Frozen gate spec — sha256-locked at registration. DO NOT edit (breaks the lock).
KILLGATE_GATES: list[Gate] = [
    {
        "name": "battles_played_gt0",
        "description": "anti-vacuous: battles_played must be > 0",
        "metric": "battles_played",
        "op": ">",
        "threshold": 0.0,
        "relative_to_baseline": False,
    },
    {
        "name": "gens_completed_gt0",
        "description": "anti-vacuous: gens_completed must be > 0",
        "metric": "gens_completed",
        "op": ">",
        "threshold": 0.0,
        "relative_to_baseline": False,
    },
    {
        "name": "win_rate_uplift",
        "description": "evolved must beat seed win_rate by >=0.10 on held-out baselines",
        "metric": "win_rate",
        "op": ">=",
        "threshold": 0.10,
        "relative_to_baseline": True,
    },
]

PROBE_NAME = "codex_harness_evolution_killgate"


def _extract_metrics(fv: CodexFitness) -> dict[str, float]:
    return {
        "win_rate": fv.win_rate,
        "battles_played": float(fv.battles_played),
        "gens_completed": float(fv.gens_completed),
    }


def build_killgate() -> Probe:
    """Return the locked kill-gate Probe (not yet registered — call .register())."""
    return Probe(
        name=PROBE_NAME,
        gates=KILLGATE_GATES,
        evaluate_fn=_extract_metrics,
    )


def open_eval_db(db_path: str | None = None) -> tuple[EngramStore, sqlite3.Connection]:
    """Open (or create) an eval database for kill-gate registration/running.

    Pass *db_path* to persist in a real bene.db; omit for in-memory (mock/test runs).
    """
    conn = sqlite3.connect(db_path or ":memory:")
    conn.row_factory = sqlite3.Row
    ensure_v2(conn)
    store = EngramStore(conn)
    return store, conn
