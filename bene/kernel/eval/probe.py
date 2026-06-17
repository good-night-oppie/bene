"""Falsifiable probes — pre-registered, hash-locked, admissibility-tested.

The KAOS v0.9 discipline, re-derived on the engram substrate (GAP-AUDIT
KAOS-6, BENE-1) and strengthened: admissibility is checked AT REGISTRATION
(a probe whose identity-baseline cannot trigger any kill gate is marked
inadmissible immediately), and verdicts/locks are engrams, queryable through
the same substrate as everything else.

Rules (D3/D6):
- The gate spec is canonicalized and sha256-locked at registration; an edited
  spec refuses to run (LockTamperError). No retune-and-rerun.
- ``run`` compares subject vs baseline metrics through the locked gates:
  any kill → REJECT; none → ACCEPT; inadmissible/unobservable → VOID.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import ulid

from bene.kernel.engrams import EngramStore
from bene.kernel.eval.gates import (
    Gate,
    canonical_spec,
    evaluate_gate,
    lock_hash,
    validate_gates,
)
from bene.kernel.eval.verdict import ACCEPT, REJECT, VOID, Verdict, persist_verdict

MetricsFn = Callable[[Any], dict[str, float]]


class LockTamperError(RuntimeError):
    """The stored gate spec no longer matches its registration-time lock."""


class ProbeNotRegistered(RuntimeError):
    pass


class ProbeInadmissible(RuntimeError):
    """The probe's baseline cannot trigger any kill gate — it cannot falsify."""


class Probe:
    def __init__(self, name: str, gates: list[Gate], evaluate_fn: MetricsFn) -> None:
        validate_gates(gates)
        self.name = name
        self.gates = gates
        self.evaluate_fn = evaluate_fn
        self.probe_id: str | None = None

    # ---------------- registration & admissibility ----------------

    def register(
        self,
        store: EngramStore,
        conn: sqlite3.Connection,
        *,
        baseline: Any,
        subject_ref: str | None = None,
    ) -> str:
        """Lock the gate spec, run the admissibility self-test, persist.

        Admissibility (falsification self-test): evaluate the baseline against
        itself — zero improvement. If NO gate kills that identity candidate,
        the probe cannot kill anything and is registered ``inadmissible``;
        attempting to run it yields VOID.
        """
        spec = canonical_spec(self.gates)
        lock = lock_hash(self.gates)
        baseline_metrics = self.evaluate_fn(baseline)
        identity_results = [
            evaluate_gate(g, baseline_metrics, baseline_metrics) for g in self.gates
        ]
        admissible = any(r["killed"] for r in identity_results)
        status = "admissible" if admissible else "inadmissible"

        self.probe_id = str(ulid.new())
        conn.execute(
            "INSERT INTO probe_registry (probe_id, name, gate_spec, lock_sha256, status, subject_ref)"
            " VALUES (?,?,?,?,?,?)",
            (self.probe_id, self.name, spec, lock, status, subject_ref),
        )
        store.append(
            "eval",
            f"probe-lock:{self.name}",
            spec,
            provenance={"system": "bene.kernel.eval"},
            metadata={"lock_sha256": lock, "status": status},
        )
        if not admissible:
            persist_verdict(
                Verdict(
                    status=VOID,
                    probe_name=self.name,
                    gate_results=identity_results,
                    reason="inadmissible: baseline identity run triggers no kill gate",
                ),
                store=store,
                conn=conn,
                probe_id=self.probe_id,
                subject_ref=subject_ref,
            )
        conn.commit()
        return self.probe_id

    # ---------------- execution ----------------

    def run(
        self,
        subject: Any,
        baseline: Any,
        *,
        store: EngramStore,
        conn: sqlite3.Connection,
        subject_ref: str | None = None,
    ) -> Verdict:
        row = conn.execute(
            "SELECT probe_id, gate_spec, lock_sha256, status, subject_ref"
            " FROM probe_registry WHERE name = ?",
            (self.name,),
        ).fetchone()
        if row is None:
            raise ProbeNotRegistered(self.name)
        probe_id, stored_spec, stored_lock, status, registered_ref = row

        # Tamper detection both ways: stored spec must hash to stored lock,
        # and the in-memory gates must match the registered spec.
        import hashlib

        if hashlib.sha256(stored_spec.encode()).hexdigest() != stored_lock:
            raise LockTamperError(f"probe {self.name}: stored gate spec does not match its lock")
        if canonical_spec(self.gates) != stored_spec:
            raise LockTamperError(
                f"probe {self.name}: in-memory gates differ from the registered, locked spec"
            )

        if status == "inadmissible":
            return persist_verdict(
                Verdict(VOID, self.name, [], reason="probe is inadmissible"),
                store=store,
                conn=conn,
                probe_id=probe_id,
                subject_ref=subject_ref or registered_ref,
            )

        subject_metrics = self.evaluate_fn(subject)
        baseline_metrics = self.evaluate_fn(baseline)
        results = [evaluate_gate(g, subject_metrics, baseline_metrics) for g in self.gates]
        status_out = REJECT if any(r["killed"] for r in results) else ACCEPT
        return persist_verdict(
            Verdict(status_out, self.name, results),
            store=store,
            conn=conn,
            probe_id=probe_id,
            subject_ref=subject_ref or registered_ref,
        )
