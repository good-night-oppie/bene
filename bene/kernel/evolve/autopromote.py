"""Close the metaharness→evolve loop: gated auto-promotion.

The metaharness already persists each evaluated candidate as a tier-4 strategic
genome engram (``search._bridge_candidate_to_evolve``), but promotion still
required a human to register a probe, run it, read the ACCEPT verdict, and call
``promote()`` by hand. These primitives automate that dance WITHOUT weakening
the kill gate: ``promote()`` still demands the ACCEPT verdict the probe writes,
so a REJECT/VOID never promotes and there is no back-door auto-flip.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from bene.kernel.engrams import EngramStore
from bene.kernel.eval import ACCEPT
from bene.kernel.eval.gates import Gate
from bene.kernel.eval.probe import Probe
from bene.kernel.evolve.gepa import promote


@dataclass(frozen=True)
class PromotionOutcome:
    candidate_engram_id: str
    promoted: bool
    status: str  # ACCEPT | REJECT | VOID
    verdict_engram: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_engram_id": self.candidate_engram_id,
            "promoted": self.promoted,
            "status": self.status,
            "verdict_engram": self.verdict_engram,
            "reason": self.reason,
        }


def build_improvement_probe(name: str, metric: str, *, delta: float = 0.0, op: str = ">") -> Probe:
    """A probe whose single gate kills unless ``(subject − baseline) op delta``
    — so ACCEPT means "the candidate improves ``metric`` over baseline". The
    identity self-test (subject == baseline → ``0 op delta`` is false → killed)
    makes the probe admissible, per the eval kill-gate contract."""
    gate: Gate = {
        "name": f"improves:{metric}",
        "description": f"{metric} improves over baseline by {op} {delta}",
        "metric": metric,
        "op": op,
        "threshold": float(delta),
        "relative_to_baseline": True,
    }
    return Probe(name, [gate], dict)  # evaluate_fn=dict: a scores dict is already metrics


def gated_promote(
    candidate_engram_id: str,
    *,
    probe: Probe,
    subject: dict[str, float],
    baseline: dict[str, float],
    store: EngramStore,
    conn: sqlite3.Connection,
) -> PromotionOutcome:
    """Run a registered probe against a candidate; promote it iff ACCEPT.

    The probe's ACCEPT verdict is linked ``verifies`` → candidate (the run's
    ``subject_ref``), which is exactly what ``promote()`` requires — so this is
    the existing kill gate, automated, not bypassed."""
    verdict = probe.run(subject, baseline, store=store, conn=conn, subject_ref=candidate_engram_id)
    if verdict.status == ACCEPT:
        promote(candidate_engram_id, store=store, conn=conn)
        return PromotionOutcome(
            candidate_engram_id, True, ACCEPT, verdict.engram_id, "promoted behind ACCEPT verdict"
        )
    return PromotionOutcome(
        candidate_engram_id,
        False,
        verdict.status,
        verdict.engram_id,
        f"held: probe returned {verdict.status} (no promotion without ACCEPT)",
    )


def auto_promote_evolved(
    candidate_engram_id: str,
    *,
    metric: str,
    subject: dict[str, float],
    baseline: dict[str, float],
    store: EngramStore,
    conn: sqlite3.Connection,
    delta: float = 0.0,
    probe_name: str | None = None,
) -> PromotionOutcome:
    """One call that closes the loop: build + register an improvement probe,
    then :func:`gated_promote`. Returns the outcome (promoted iff the candidate
    beats ``baseline`` on ``metric`` by more than ``delta``)."""
    probe = build_improvement_probe(
        probe_name or f"auto-promote:{candidate_engram_id}", metric, delta=delta
    )
    probe.register(store, conn, baseline=baseline, subject_ref=candidate_engram_id)
    return gated_promote(
        candidate_engram_id, probe=probe, subject=subject, baseline=baseline, store=store, conn=conn
    )
