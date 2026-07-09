#!/usr/bin/env python3
"""accuracy_gate.py — sha256-locked BENE eval-gate over shipped-copy ACCURACY.

Wraps exec_probes.run_all() (PROBE-EXEC-01 install-resolves + DOC-HARDNUM
doc↔db cross-check) in a hash-locked bene Probe so "the landing/docs are
accuracy-clean" is a falsifiable ACCEPT/REJECT verdict, not a vibe. Same
mechanism as harness-engineering's substack_scrub_gate.py.

  Gate G_accuracy_clean : failures <= 0   (absolute; failures = exec_probes BLOCKs)
  Baseline = a synthetic known-bad state (failures=1) so the identity self-test
             is KILLED → the probe is ADMISSIBLE (a gate you cannot fail is void).

  ACCEPT  → shipped copy is accuracy-clean → safe to ship.
  REJECT  → a real accuracy regression is live (`uv add bene`, schema.md lie, …)
            → CI fails. This is the gate that makes the class unable to silently
            recur — wire it as a required CI step + run it pre-ship.

Run:  uv run --project /home/admin/gh/bene-main python scripts/landing_copy_linter/accuracy_gate.py [register|check|demo]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import exec_probes  # noqa: E402
from bene import Bene  # noqa: E402
from bene.kernel import EngramStore, ensure_v2  # noqa: E402
from bene.kernel.eval import ACCEPT, REJECT, Probe  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GATE_DB = Path(os.environ.get("ACCURACY_GATE_DB", REPO / ".harness/landing-docs-accuracy-gate.db"))
PROBE_NAME = "landing-docs-accuracy"

GATES = [
    {
        "name": "G_accuracy_clean",
        "description": "0 executable-probe BLOCK findings (install resolves + doc numbers match the real db)",
        "metric": "failures",
        "op": "<=",
        "threshold": 0,
        "relative_to_baseline": False,
    },
]


def measure(subject) -> dict:
    """subject 'live' → run the probes against the real repo; 'baseline' → a
    synthetic failing state (makes the gate admissible)."""
    if subject == "live":
        res = exec_probes.run_all()
        return {"failures": float(res["failure_count"]), "_findings": res["findings"]}
    return {"failures": 1.0}  # synthetic known-bad baseline


def _store(db):
    ensure_v2(db.conn)
    return EngramStore(db.conn, db.blobs)


def cmd_register():
    GATE_DB.parent.mkdir(parents=True, exist_ok=True)
    db = Bene(str(GATE_DB))
    store = _store(db)
    cand = store.append(
        "strategic",
        "landing-docs-accuracy-deliverable",
        "shipped copy resolves + doc numbers match the real db",
        tier=4,
        provenance={"agent_id": "harness-7"},
    )
    probe = Probe(PROBE_NAME, GATES, measure)
    pid = probe.register(store, db.conn, baseline="baseline", subject_ref=cand)
    row = db.conn.execute(
        "SELECT status, lock_sha256 FROM probe_registry WHERE name=?", (PROBE_NAME,)
    ).fetchone()
    print(f"registered probe_id={pid}  status={row[0]}  lock={row[1][:16]}…")
    print("  admissible: synthetic-bad baseline (failures=1) is killed by G_accuracy_clean")
    db.close()


def cmd_check():
    GATE_DB.parent.mkdir(parents=True, exist_ok=True)
    db = Bene(str(GATE_DB))
    store = _store(db)
    registered = db.conn.execute(
        "SELECT 1 FROM probe_registry WHERE name=?", (PROBE_NAME,)
    ).fetchone()
    if registered is None:
        cand = store.append(
            "strategic",
            "landing-docs-accuracy-deliverable",
            "shipped copy resolves + doc numbers match the real db",
            tier=4,
            provenance={"agent_id": "harness-7"},
        )
        Probe(PROBE_NAME, GATES, measure).register(
            store, db.conn, baseline="baseline", subject_ref=cand
        )
    probe = Probe(PROBE_NAME, GATES, measure)
    v = probe.run("live", "baseline", store=store, conn=db.conn)
    m = measure("live")
    print(f"VERDICT={v.status}  failures={int(m['failures'])}")
    for f in m.get("_findings", []):
        if f["severity"] == "BLOCK":
            print(f"    [{f['probe']}] {f['file']}:{f['line']} — {f['detail']}")
    if v.status == ACCEPT:
        print("  → ACCURATE. Shipped copy resolves + doc numbers match the real db. Safe to ship.")
    elif v.status == REJECT:
        print(
            "  → REGRESSION LIVE. Fix the findings above (or add a source spec / disclosure) before ship."
        )
    else:
        print("  → VOID (inadmissible) — gate is fake; rewrite it.")
    db.close()
    return v.status


def cmd_demo():
    print("== current repo (expect REJECT — the live regressions) ==")
    cmd_check()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"register": cmd_register, "check": cmd_check, "demo": cmd_demo}.get(cmd, cmd_check)()
