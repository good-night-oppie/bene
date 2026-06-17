"""Lighthouse trace probe — reproduces PASS-31 from the adx dogfood stream.

The dogfood loop shipped a GREEN test for cross-substrate ``session_id``
propagation that looked like::

    assert isinstance(session_id_propagated, bool)   # passes for True AND False

That gate checks the *shape* of the value, not whether propagation actually
happened — so a broken environment (propagation silently ``False``) still had a
passing test. This example re-expresses the situation as two bene ``Probe``\\s
over the same measurement and shows the hash-locked kill gate catch what the
shape assertion could not:

1. **Shape gate** (the bad one): "the propagated value is a bool". The baseline
   already satisfies it, so bene's admissibility self-test registers it
   ``inadmissible`` and running it yields ``VOID`` — bene refuses a gate that
   cannot fail (*"a gate you cannot fail is not a gate"*).
2. **Falsifiable gate** (the good one): "propagation actually observed
   (``propagated_true >= 1``)". Registers ``admissible``, ``REJECT``\\s the
   broken (propagation ``False``) environment, and ``ACCEPT``\\s the real fix
   (propagation ``True``).

The "propagation" metric is a stand-in (a function returning True/False); the
point is the GATE shape, not a live langfuse trace. See ``docs/probe-authoring.md``
for the authoring rule this example embodies.

Run::

    uv run python examples/lighthouse_trace_probe.py
"""

from __future__ import annotations

import sqlite3

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe


def measure(propagation_works: bool) -> dict[str, float]:
    """Model the dogfood's measurement of ``session_id`` propagation to a child
    span.

    ``is_bool`` is the *shape* the bad test checked — always ``1.0`` because the
    value is a bool whether or not propagation worked. ``propagated_true`` is the
    *semantics* — ``1.0`` only when the session_id actually reached the child.
    """
    return {
        "is_bool": 1.0,  # isinstance(propagated, bool) — True for both True and False
        "propagated_true": 1.0 if propagation_works else 0.0,
    }


# The bad gate: a shape check the baseline already passes -> inadmissible.
SHAPE_GATE = {
    "name": "session_id_is_bool",
    "description": "the propagated value is a bool — a shape check that cannot fail",
    "metric": "is_bool",
    "op": ">=",
    "threshold": 1.0,
}
# The good gate: did the session_id actually propagate? -> falsifiable.
FALSIFIABLE_GATE = {
    "name": "session_id_propagated",
    "description": "session_id actually reached the child span (propagated_true >= 1)",
    "metric": "propagated_true",
    "op": ">=",
    "threshold": 1.0,
}

BROKEN = False  # propagation silently fails (the live dogfood environment)
FIXED = True  # propagation works (the real fix)


def _status(conn: sqlite3.Connection, name: str) -> str:
    return conn.execute("SELECT status FROM probe_registry WHERE name = ?", (name,)).fetchone()[0]


def run_lighthouse() -> dict[str, object]:
    """Register + run both probes on an in-memory Bene; return the outcomes.

    Returns a dict with the shape gate's registration status + run verdict, and
    the falsifiable probe's registration status + broken/fixed verdicts (incl.
    the killed gates on the broken run).
    """
    b = Bene(":memory:")
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)

    # 1. The shape gate registers inadmissible and runs VOID.
    shape = Probe("shape-isinstance", [SHAPE_GATE], measure)
    shape.register(store, b.conn, baseline=BROKEN)
    shape_status = _status(b.conn, "shape-isinstance")
    shape_verdict = shape.run(BROKEN, BROKEN, store=store, conn=b.conn)

    # 2. The falsifiable probe registers admissible; REJECT broken, ACCEPT fixed.
    probe = Probe("propagation-observed", [FALSIFIABLE_GATE], measure)
    probe.register(store, b.conn, baseline=BROKEN)
    probe_status = _status(b.conn, "propagation-observed")
    broken = probe.run(BROKEN, BROKEN, store=store, conn=b.conn)
    fixed = probe.run(FIXED, BROKEN, store=store, conn=b.conn)

    b.close()
    return {
        "shape_status": shape_status,
        "shape_verdict": shape_verdict.status,
        "probe_status": probe_status,
        "broken_verdict": broken.status,
        "broken_killed": broken.killed_gates,
        "fixed_verdict": fixed.status,
    }


def main() -> int:
    r = run_lighthouse()
    print(f"[shape gate ] registration: {r['shape_status']}")
    print(
        f"[shape gate ] run verdict : {r['shape_verdict']}  (bene refuses a gate that cannot fail)"
    )
    print(f"[falsifiable] registration: {r['probe_status']}")
    print(f"[falsifiable] broken env  : {r['broken_verdict']}  (killed: {r['broken_killed']})")
    print(f"[falsifiable] fixed env   : {r['fixed_verdict']}")
    print()

    ok = (
        r["shape_status"] == "inadmissible"
        and r["shape_verdict"] == "VOID"
        and r["probe_status"] == "admissible"
        and r["broken_verdict"] == "REJECT"
        and r["fixed_verdict"] == "ACCEPT"
    )
    print(
        "PASS-31 reproduced: shape gate VOID, broken REJECT, fixed ACCEPT ✓"
        if ok
        else "NOT reproduced ✗"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
