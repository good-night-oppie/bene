"""Spec-as-artifact SDD gating — proposal → ACCEPT-gated → spec.

The engram kinds ``proposal`` and ``spec`` already exist; what was missing is
the gating workflow that turns a *proposal* into an accepted *spec* only behind
a recorded ACCEPT verdict. This mirrors the evolve kill gate: a spec is created
ONLY when an ACCEPT eval engram (from a probe) OR a named-human decision gates
the proposal — never anonymously, never auto. The spec engram is
``derived_from`` the proposal and ``gated_by`` the verdict, so the acceptance
chain is fully auditable through ``engram_links``.

Append-only: a proposal/spec/verdict is never mutated. Status is derived from
the link graph — a proposal with a ``spec`` derived from it is *accepted*; one
with a recorded rejection is *rejected*; otherwise *proposed*.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from bene.kernel.engrams import EngramStore

PROPOSED, ACCEPTED, REJECTED = "proposed", "accepted", "rejected"


class SpecGateBlocked(PermissionError):
    """No ACCEPT verdict (probe or named human) gates this proposal."""


@dataclass(frozen=True)
class ProposalView:
    proposal_id: str
    title: str
    status: str
    spec_id: str | None
    verdict_engram: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "status": self.status,
            "spec_id": self.spec_id,
            "verdict_engram": self.verdict_engram,
        }


class SpecWorkflow:
    def __init__(self, store: EngramStore, conn: sqlite3.Connection) -> None:
        self.store = store
        self.conn = conn

    # ---------------- propose ----------------

    def propose(
        self,
        title: str,
        body: str,
        *,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        prov = {"agent_id": agent_id} if agent_id else {"system": "bene.kernel.spec"}
        return self.store.append(
            "proposal",
            title,
            body,
            provenance=prov,
            agent_id=agent_id,
            metadata={"sdd": True, "kind": "proposal", **(metadata or {})},
        )

    # ---------------- gate ----------------

    def _verify_accept_verdict(self, verdict_engram_id: str) -> None:
        e = self.store.get(verdict_engram_id)
        if e.kind != "eval" or e.metadata.get("status") != "ACCEPT":
            raise SpecGateBlocked(
                f"{verdict_engram_id} is not an ACCEPT eval verdict (kind={e.kind!r},"
                f" status={e.metadata.get('status')!r})"
            )

    def _record_human_accept(self, proposal_id: str, decided_by: str, rationale: str) -> str:
        return self.store.append(
            "eval",
            f"spec-accept:{proposal_id}",
            json.dumps({"status": "ACCEPT", "decided_by": decided_by, "rationale": rationale}),
            provenance={"system": "bene.kernel.spec"},
            parents=[proposal_id],
            link_type="verifies",
            metadata={"status": "ACCEPT", "decided_by": decided_by, "sdd": True},
        )

    def accept(
        self,
        proposal_id: str,
        *,
        verdict_engram_id: str | None = None,
        decided_by: str = "",
        rationale: str = "",
    ) -> str:
        """Promote a proposal to an accepted ``spec`` — ONLY behind an ACCEPT
        verdict. Pass ``verdict_engram_id`` (a probe's ACCEPT eval engram) for
        the probe-gated path, or ``decided_by='human:<name>'`` for the named
        human-grant path. Raises :class:`SpecGateBlocked` otherwise."""
        self.store.get(proposal_id)  # existence check
        if verdict_engram_id is not None:
            self._verify_accept_verdict(verdict_engram_id)
            verdict_id = verdict_engram_id
        elif decided_by.startswith("human:"):
            verdict_id = self._record_human_accept(proposal_id, decided_by, rationale)
        else:
            raise SpecGateBlocked(
                "accept requires an ACCEPT verdict_engram_id or decided_by='human:<name>'"
            )

        spec_id = self.store.append(
            "spec",
            f"spec:{self.store.get(proposal_id).title}",
            self.store.payload(proposal_id).decode(errors="replace"),
            provenance={"system": "bene.kernel.spec"},
            parents=[proposal_id],
            link_type="derived_from",
            metadata={
                "sdd": True,
                "kind": "spec",
                "proposal_id": proposal_id,
                "verdict_engram": verdict_id,
                "decided_by": decided_by or "probe",
                "rationale": rationale,
            },
        )
        self.store.link(spec_id, verdict_id, "gated_by")
        self.conn.commit()
        return spec_id

    def reject(self, proposal_id: str, *, decided_by: str = "human", rationale: str = "") -> str:
        """Record a rejection (append-only intervention engram refutes→proposal)."""
        self.store.get(proposal_id)
        rid = self.store.append(
            "intervention",
            f"spec-reject:{proposal_id}",
            json.dumps({"status": "REJECTED", "decided_by": decided_by, "rationale": rationale}),
            provenance={"system": "bene.kernel.spec"},
            parents=[proposal_id],
            link_type="refutes",
            metadata={"sdd": True, "rejected": True, "decided_by": decided_by},
        )
        self.conn.commit()
        return rid

    # ---------------- read ----------------

    def spec_for(self, proposal_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT e.engram_id FROM engram_links l JOIN engrams e ON e.engram_id = l.src_id"
            " WHERE l.link_type='derived_from' AND l.dst_id=? AND e.kind='spec'"
            " ORDER BY e.created_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        return row[0] if row else None

    def _has_rejection(self, proposal_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM engram_links l JOIN engrams e ON e.engram_id = l.src_id"
            " WHERE l.link_type='refutes' AND l.dst_id=? AND e.kind='intervention'"
            " AND e.metadata LIKE '%\"rejected\": true%' LIMIT 1",
            (proposal_id,),
        ).fetchone()
        return row is not None

    def status(self, proposal_id: str) -> str:
        if self.spec_for(proposal_id) is not None:
            return ACCEPTED
        if self._has_rejection(proposal_id):
            return REJECTED
        return PROPOSED

    def view(self, proposal_id: str) -> ProposalView:
        e = self.store.get(proposal_id)
        spec_id = self.spec_for(proposal_id)
        verdict = self.store.get(spec_id).metadata.get("verdict_engram") if spec_id else None
        return ProposalView(proposal_id, e.title, self.status(proposal_id), spec_id, verdict)

    def ls(self, *, limit: int = 50) -> list[ProposalView]:
        rows = self.conn.execute(
            "SELECT engram_id FROM engrams WHERE kind='proposal'"
            " AND metadata LIKE '%\"sdd\": true%' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self.view(r[0]) for r in rows]
