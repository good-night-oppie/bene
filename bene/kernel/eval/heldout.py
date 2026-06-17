"""Held-out promotion gate (C2, 防偷懒) — kill-gated on a disjoint, hash-locked set.

A candidate that overfits its training battles must not be promotable. So the
promotion probe scores on a HELD-OUT set that is *provably disjoint* from the CRN
windows the candidate tuned on:

1. **Held-out manifest** = a content-addressed frozen set of
   ``(opponent_checkpoint, seed, scenario)`` tuples — sha256 set-hash, registered
   as a hash-locked eval engram (frozen-per-run; rotate a fresh manifest between
   runs).
2. **Disjointness** ``heldout ∩ training = ∅`` is verified over the per-tuple
   hashes BEFORE any scoring; overlap ⇒ **VOID** (an inadmissible eval — the
   candidate is never even scored, so overfit data can't earn a promotion).
3. **Score + gate**: the held-out objective must beat the incumbent by a
   pre-registered ``margin`` (a ``relative_to_baseline`` gate — margin>0 makes the
   identity self-test falsifiable, so "must strictly beat the incumbent" is
   enforced by admissibility). ACCEPT iff it beats by the margin; REJECT else.
4. On **ACCEPT** the promotion is stamped with all three hashes
   (``probe_lock`` / ``heldout_manifest`` / ``training_manifest``) so the
   promotion is post-hoc provable as "scored on data it never trained on".

Cross-team (B1): bene owns the manifest lock, the disjointness proof, scoring, and
the A/R/V verdict; adx EXECUTES the battles via an injected
``run_heldout(tuples, agent) -> float``. bene never runs battles.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from bene.kernel.engrams import EngramStore
from bene.kernel.eval.gates import Gate, lock_hash
from bene.kernel.eval.probe import Probe
from bene.kernel.eval.verdict import ACCEPT, VOID, Verdict, persist_verdict

#: adx supplies this: score one agent (candidate or incumbent) over the tuples.
RunHeldout = Callable[[list, object], float]

HELDOUT_METRIC = "heldout_objective"


def _tuple_hash(t) -> str:
    return hashlib.sha256(json.dumps(list(t), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class HeldoutManifest:
    """A frozen, content-addressed set of (opponent_checkpoint, seed, scenario)."""

    tuples: tuple[tuple, ...]

    @classmethod
    def of(cls, tuples) -> HeldoutManifest:
        norm = tuple((str(o), int(s), str(sc)) for (o, s, sc) in tuples)
        return cls(norm)

    @property
    def tuple_hashes(self) -> frozenset[str]:
        return frozenset(_tuple_hash(t) for t in self.tuples)

    @property
    def manifest_hash(self) -> str:
        canonical = json.dumps(sorted(list(t) for t in self.tuples), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


def disjoint(heldout: HeldoutManifest, training: HeldoutManifest) -> bool:
    """True iff no held-out tuple was in the candidate's training set."""
    return not (heldout.tuple_hashes & training.tuple_hashes)


def build_heldout_probe(
    manifest: HeldoutManifest,
    run_heldout: RunHeldout,
    *,
    margin: float,
    name: str | None = None,
) -> Probe:
    """A Probe whose single gate kills unless the held-out objective beats the
    incumbent by ``margin``. The probe name embeds the manifest hash, so a
    different held-out set is a different locked probe."""
    gate: Gate = {
        "name": "heldout-beats-incumbent",
        "description": f"held-out objective must beat incumbent by >= {margin}",
        "metric": HELDOUT_METRIC,
        "op": ">=",
        "threshold": float(margin),
        "relative_to_baseline": True,
    }
    probe_name = name or f"heldout::{manifest.manifest_hash[:12]}"

    def evaluate_fn(agent):
        return {HELDOUT_METRIC: float(run_heldout(list(manifest.tuples), agent))}

    return Probe(probe_name, [gate], evaluate_fn)


class HeldoutGate:
    """Register + run the held-out promotion gate with disjointness + hash stamping."""

    def __init__(self, store: EngramStore, conn: sqlite3.Connection) -> None:
        self.store = store
        self.conn = conn

    def register(self, probe: Probe, manifest: HeldoutManifest, *, incumbent) -> str:
        """Freeze the manifest as a hash-locked engram and register the probe
        (admissibility self-test against the incumbent baseline)."""
        self.store.append(
            "eval",
            f"heldout-manifest:{manifest.manifest_hash[:12]}",
            json.dumps([list(t) for t in manifest.tuples]),
            provenance={"system": "bene.kernel.eval.heldout"},
            metadata={"manifest_sha256": manifest.manifest_hash, "n_tuples": len(manifest.tuples)},
        )
        return probe.register(self.store, self.conn, baseline=incumbent, subject_ref=None)

    def score(
        self,
        probe: Probe,
        manifest: HeldoutManifest,
        *,
        candidate,
        incumbent,
        training: HeldoutManifest,
        subject_ref: str | None = None,
    ) -> dict:
        """Disjointness gate → probe run → 3-hash stamp on ACCEPT.

        Returns ``{"verdict", "stamp"}`` where ``stamp`` (present only on ACCEPT)
        is the non-gameable promotion record.
        """
        if not disjoint(manifest, training):
            overlap = len(manifest.tuple_hashes & training.tuple_hashes)
            verdict = persist_verdict(
                Verdict(
                    VOID,
                    probe.name,
                    [],
                    reason=f"held-out ∩ training not disjoint: {overlap} tuple(s) overlap (overfit guard)",
                ),
                store=self.store,
                conn=self.conn,
                subject_ref=subject_ref,
            )
            return {"verdict": verdict, "stamp": None}

        verdict = probe.run(
            candidate, incumbent, store=self.store, conn=self.conn, subject_ref=subject_ref
        )

        stamp = None
        if verdict.status == ACCEPT:
            stamp = {
                "probe_lock_sha256": lock_hash(probe.gates),
                "heldout_manifest_sha256": manifest.manifest_hash,
                "training_manifest_sha256": training.manifest_hash,
            }
            self.store.append(
                "eval",
                f"heldout-promotion-stamp:{probe.name}",
                json.dumps({"candidate": str(candidate), **stamp}),
                provenance={"system": "bene.kernel.eval.heldout"},
                metadata=stamp,
            )
        return {"verdict": verdict, "stamp": stamp}
