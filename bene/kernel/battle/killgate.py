"""Hash-locked kill-gate probe for battle harness evolution — Lane B / B3.

Gates are frozen at import time; editing them and running the probe raises
LockTamperError (the tamper-detection property of bene.kernel.eval.probe).

Three gates (all required for ACCEPT):
  win_rate_uplift     — evolved must beat seed by ≥10pp on held-out (relative)
  battles_played_gt0  — anti-vacuous: at least one real battle was played
  gens_completed_gt0  — anti-vacuous: at least one evolution generation ran

The gate spec is sha256-locked at registration; the lock is recorded in
probe_registry and re-checked on every run.  A harness identical to seed
shows 0 win_rate uplift → gate kills → probe IS admissible (falsifiable).

Usage::

    store, conn = open_eval_db()           # or pass db_path for persistence
    probe = build_killgate()
    probe.register(store, conn, baseline=seed_fv_with_gens(0))

    verdict = probe.run(
        subject=evolved_fv_with_gens(n_gen),
        baseline=seed_fv_with_gens(0),
        store=store, conn=conn,
        subject_ref=best_harness.harness_id,
    )
    assert verdict.status == ACCEPT        # or handle REJECT / VOID
"""

from __future__ import annotations

import sqlite3

from bene.kernel.battle.genome import FitnessVector
from bene.kernel.engrams import EngramStore
from bene.kernel.eval.gates import Gate
from bene.kernel.eval.probe import Probe
from bene.kernel.schema_v2 import ensure_v2

# ---------------------------------------------------------------------------
# Frozen gate spec — sha256 lock recorded at registration time.
# DO NOT edit these dicts; that would break the lock and raise LockTamperError.
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

PROBE_NAME = "battle_harness_evolution_killgate"


def _extract_metrics(fv: FitnessVector) -> dict[str, float]:
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


def open_eval_db(
    db_path: str | None = None,
) -> tuple[EngramStore, sqlite3.Connection]:
    """Open (or create) an eval database for kill-gate registration/running.

    Pass *db_path* to persist results in a real bene.db; omit for in-memory
    (useful in tests and mock-fitness runs where persistence isn't needed).
    """
    conn = sqlite3.connect(db_path or ":memory:")
    conn.row_factory = sqlite3.Row
    ensure_v2(conn)
    store = EngramStore(conn)
    return store, conn
