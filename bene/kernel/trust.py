"""Trust ledger — computed, never declared (D8).

Per-agent trust is derived from verifiable records in the database. Four
documented, deterministic signals, each in [0, 1]:

- ``verification_coverage`` — of the agent's authored knowledge artifacts
  (procedural/strategic engrams), the fraction carrying a ``verifies`` link
  from an eval engram. No artifacts → 1.0 (vacuously covered, flagged).
- ``audit_completeness`` — fraction of the agent's tool calls with a recorded
  terminal outcome (success/error + output). No calls → 1.0 (flagged).
- ``checkpoint_discipline`` — checkpoints per 50-event window, capped at 1.0.
  Fewer than 10 events → 1.0 (probation window too small to judge, flagged).
- ``outcome_reliability`` — recency-weighted tool-call success rate with
  exponential rank decay (half-life = 20 calls). No calls → 0.5 (unknown).

``composite`` = 0.30·verification + 0.25·audit + 0.20·checkpoint
+ 0.25·reliability. Components are always reported alongside the composite —
never a single magic number (jaggedness: H-lens).

Denials and other trust-relevant moments are recorded as ``trust`` engrams.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from bene.kernel.engrams import EngramStore

WEIGHTS = {
    "verification_coverage": 0.30,
    "audit_completeness": 0.25,
    "checkpoint_discipline": 0.20,
    "outcome_reliability": 0.25,
}
HALF_LIFE_CALLS = 20
EVENTS_PER_CHECKPOINT = 50
LEVEL_THRESHOLDS = {3: 0.60, 4: 0.75}


class TrustLedger:
    def __init__(self, conn: sqlite3.Connection, store: EngramStore | None = None) -> None:
        self.conn = conn
        self.store = store

    # ---------------- signals ----------------

    def verification_coverage(self, agent_id: str) -> tuple[float, str]:
        authored = [
            r[0]
            for r in self.conn.execute(
                "SELECT engram_id FROM engrams WHERE agent_id = ?"
                " AND kind IN ('procedural','strategic')",
                (agent_id,),
            ).fetchall()
        ]
        if not authored:
            return 1.0, "no authored artifacts (vacuous)"
        placeholders = ",".join("?" * len(authored))
        verified = self.conn.execute(
            f"SELECT COUNT(DISTINCT l.dst_id) FROM engram_links l"
            f" JOIN engrams e ON e.engram_id = l.src_id"
            f" WHERE l.link_type = 'verifies' AND e.kind = 'eval'"
            f" AND l.dst_id IN ({placeholders})",
            authored,
        ).fetchone()[0]
        return verified / len(authored), f"{verified}/{len(authored)} artifacts verified"

    def audit_completeness(self, agent_id: str) -> tuple[float, str]:
        total = self.conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
        if total == 0:
            return 1.0, "no tool calls (vacuous)"
        complete = self.conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE agent_id = ?"
            " AND status IN ('success','error') AND output IS NOT NULL",
            (agent_id,),
        ).fetchone()[0]
        return complete / total, f"{complete}/{total} calls with recorded outcome"

    def checkpoint_discipline(self, agent_id: str) -> tuple[float, str]:
        events = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
        if events < 10:
            return 1.0, f"probation window too small ({events} events)"
        checkpoints = self.conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
        expected = max(1, events // EVENTS_PER_CHECKPOINT)
        return min(1.0, checkpoints / expected), (
            f"{checkpoints} checkpoints over {events} events (expected ≥{expected})"
        )

    def outcome_reliability(self, agent_id: str) -> tuple[float, str]:
        rows = self.conn.execute(
            "SELECT status FROM tool_calls WHERE agent_id = ?"
            " AND status IN ('success','error') ORDER BY started_at DESC",
            (agent_id,),
        ).fetchall()
        if not rows:
            return 0.5, "no terminal tool calls (unknown)"
        num = den = 0.0
        for rank, (status,) in enumerate(rows):
            w = math.exp(-math.log(2) * rank / HALF_LIFE_CALLS)
            num += w * (1.0 if status == "success" else 0.0)
            den += w
        return num / den, f"recency-weighted over {len(rows)} calls"

    # ---------------- composite & consumers ----------------

    def summary(self, agent_id: str, *, domain: str = "*") -> dict[str, Any]:
        signals: dict[str, Any] = {}
        composite = 0.0
        for name, weight in WEIGHTS.items():
            value, note = getattr(self, name)(agent_id)
            signals[name] = {"value": round(value, 4), "weight": weight, "note": note}
            composite += weight * value
        denials = self.conn.execute(
            "SELECT COUNT(*) FROM engrams WHERE kind='trust' AND agent_id = ?"
            " AND title LIKE 'denial:%'",
            (agent_id,),
        ).fetchone()[0]
        return {
            "agent_id": agent_id,
            "domain": domain,
            "signals": signals,
            "denials": denials,
            "composite": round(composite, 4),
        }

    def record(self, agent_id: str, signal: str, value: dict[str, Any]) -> str:
        if self.store is None:
            raise RuntimeError("TrustLedger.record requires an EngramStore")
        return self.store.append(
            "trust",
            f"{signal}:{agent_id}",
            json.dumps(value),
            provenance={"system": "bene.kernel.trust"},
            agent_id=agent_id,
            metadata={"signal": signal},
        )

    def eligible(self, agent_id: str, level: int, *, domain: str = "*") -> bool:
        """Advisory eligibility: L0–L2 always; L3/L4 need the composite
        threshold, and L3+ needs at least one ACCEPT verdict touching the
        agent's artifacts (verification is earned, not asserted)."""
        if level <= 2:
            return True
        s = self.summary(agent_id, domain=domain)
        if s["composite"] < LEVEL_THRESHOLDS.get(level, 1.01):
            return False
        accepted = self.conn.execute(
            "SELECT COUNT(*) FROM engram_links l JOIN engrams e ON e.engram_id = l.src_id"
            " JOIN engrams subj ON subj.engram_id = l.dst_id"
            " WHERE l.link_type='verifies' AND e.kind='eval' AND subj.agent_id = ?",
            (agent_id,),
        ).fetchone()[0]
        return accepted >= 1

    def weighted_vote(self, agent_id: str) -> float:
        """Vote weight for shared-log tallies: 0.5 (unknown) … 1.0 (fully trusted)."""
        return 0.5 + 0.5 * self.summary(agent_id)["composite"]
