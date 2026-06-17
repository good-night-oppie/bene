"""Verdicts — ACCEPT / REJECT / VOID, persisted as eval engrams.

A verdict is never free-floating: it is an engram with provenance and a
``verifies`` (ACCEPT) or ``refutes`` (REJECT) link to the subject engram when
one is given, plus an ``experiment_runs`` row. Design: D6 in
docs/design/DESIGN-RATIONALE.md.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import ulid

from bene.kernel.engrams import EngramStore

ACCEPT = "ACCEPT"
REJECT = "REJECT"
VOID = "VOID"


@dataclass(frozen=True)
class Verdict:
    status: str  # ACCEPT | REJECT | VOID
    probe_name: str
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    engram_id: str | None = None

    @property
    def killed_gates(self) -> list[str]:
        return [g["name"] for g in self.gate_results if g.get("killed")]


def persist_verdict(
    verdict: Verdict,
    *,
    store: EngramStore,
    conn: sqlite3.Connection,
    probe_id: str | None = None,
    subject_ref: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> Verdict:
    """Persist as an eval engram + experiment_runs row; returns the verdict
    with its engram_id filled in."""
    payload = json.dumps(
        {
            "status": verdict.status,
            "probe": verdict.probe_name,
            "gate_results": verdict.gate_results,
            "reason": verdict.reason,
        },
        indent=1,
    )
    eid = store.append(
        "eval",
        f"verdict:{verdict.probe_name}:{verdict.status}",
        payload,
        provenance=provenance or {"system": "bene.kernel.eval"},
        metadata={"status": verdict.status, "probe": verdict.probe_name},
    )
    if subject_ref is not None:
        link_type = "verifies" if verdict.status == ACCEPT else "refutes"
        store.link(eid, subject_ref, link_type)
    conn.execute(
        "INSERT INTO experiment_runs (run_id, kind, probe_id, verdict_engram, summary, metrics)"
        " VALUES (?,?,?,?,?,?)",
        (
            str(ulid.new()),
            "probe",
            probe_id,
            eid,
            f"{verdict.probe_name} -> {verdict.status}"
            + (f" (killed: {', '.join(verdict.killed_gates)})" if verdict.killed_gates else ""),
            json.dumps({"gates": len(verdict.gate_results)}),
        ),
    )
    conn.commit()
    return Verdict(
        status=verdict.status,
        probe_name=verdict.probe_name,
        gate_results=verdict.gate_results,
        reason=verdict.reason,
        engram_id=eid,
    )
