"""Autonomy ladder — enforced at the capability boundary, not in markdown.

KAOS's AUTONOMY_THRESHOLD.md is doc-only (`grep autonomy kaos/ = 0 hits`,
GAP-AUDIT KAOS-3); BENE 0.1.0's control is binary run/kill (BENE-7). Here the
ladder is code: L0 Observe → L1 Suggest → L2 Act-in-sandbox → L3
Act-on-shared-state → L4 Autonomous-promote (BENE2-DESIGN §3). Grants are
per-agent and per-domain (jaggedness: an agent can be L3 at code review and
L1 at deployment). Every denial is a trust engram — the ledger sees it (D8).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from functools import wraps
from typing import Any

from bene.kernel.capabilities import AutonomyDenied, Capability
from bene.kernel.engrams import EngramStore

LEVELS = {
    0: "observe",
    1: "suggest",
    2: "act-in-sandbox",
    3: "act-on-shared-state",
    4: "autonomous-promote",
}


class AutonomyPolicy:
    def __init__(
        self,
        conn: sqlite3.Connection,
        store: EngramStore | None = None,
        *,
        default_level: int = 0,
    ) -> None:
        # default_level is a config-driven floor for every domain (kernel.autonomy
        # defaults). Capped below L4: the threshold crossing into autonomous
        # promotion is ALWAYS an explicit human grant, never a config default.
        if not (0 <= default_level <= 3):
            raise ValueError("default_level must be 0..3 (L4 is human-grant-only, never a default)")
        self.conn = conn
        self.store = store
        self.default_level = default_level

    def grant(self, agent_id: str, level: int, *, domain: str = "*", granted_by: str) -> None:
        if level not in LEVELS:
            raise ValueError(f"level must be 0..4, got {level}")
        if level == 4 and not granted_by.startswith("human:"):
            raise ValueError(
                "L4 (autonomous-promote) requires an explicit human grant "
                "(granted_by='human:<name>') — the threshold crossing is a human decision"
            )
        self.conn.execute(
            "INSERT INTO autonomy_grants (agent_id, domain, level, granted_by) VALUES (?,?,?,?)"
            " ON CONFLICT(agent_id, domain) DO UPDATE SET level=excluded.level,"
            " granted_by=excluded.granted_by, revoked_at=NULL",
            (agent_id, domain, level, granted_by),
        )
        self.conn.commit()

    def revoke(self, agent_id: str, *, domain: str = "*") -> None:
        self.conn.execute(
            "UPDATE autonomy_grants SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f','now')"
            " WHERE agent_id = ? AND domain = ?",
            (agent_id, domain),
        )
        self.conn.commit()

    def level_for(self, agent_id: str, *, domain: str = "*") -> int:
        """Effective level: max of the specific-domain and general grants
        (un-revoked), floored at the configured ``default_level``. Unknown
        agents fall to ``default_level`` (0 unless configured otherwise)."""
        rows = self.conn.execute(
            "SELECT level FROM autonomy_grants WHERE agent_id = ?"
            " AND domain IN (?, '*') AND revoked_at IS NULL",
            (agent_id, domain),
        ).fetchall()
        granted = max((r[0] for r in rows), default=0)
        return max(granted, self.default_level)  # default_level is a floor

    def auto_promote(
        self,
        agent_id: str,
        ledger: Any,
        *,
        domain: str = "*",
        granted_by: str = "trust:auto",
        max_level: int = 3,
    ) -> int | None:
        """Raise an agent to the highest level it is trust-ELIGIBLE for, capped at
        ``max_level`` and HARD-capped below L4 — the crossing into
        autonomous-promote is always an explicit human grant, never trust-driven.

        This is the real caller of ``TrustLedger.eligible`` (which is otherwise
        advisory with zero callers): tiers L0–L3 auto-promote once the computed
        trust composite + a probe ACCEPT clear the bar (``ledger`` is duck-typed —
        anything exposing ``eligible(agent_id, level, *, domain)``). No-op
        (returns ``None``) when the agent is already at/above its eligible level;
        otherwise grants the new level and records a trust engram. L4 is never
        reached here regardless of ``max_level``.
        """
        cap = min(int(max_level), 3)  # L4 is never auto-granted
        current = self.level_for(agent_id, domain=domain)
        target = current
        for lvl in range(current + 1, cap + 1):
            if ledger.eligible(agent_id, lvl, domain=domain):
                target = lvl
            else:
                break  # thresholds are monotone in level — stop at the first miss
        if target <= current:
            return None
        self.grant(agent_id, target, domain=domain, granted_by=granted_by)
        if self.store is not None:
            self.store.append(
                "trust",
                f"auto-promote:{agent_id}",
                json.dumps(
                    {"from": current, "to": target, "domain": domain, "granted_by": granted_by}
                ),
                provenance={"system": "bene.kernel.harness.autonomy"},
                agent_id=agent_id,
                metadata={"signal": "auto_promote", "level": target},
            )
        return target

    def check(self, agent_id: str, capability: Capability) -> bool:
        """The enforcement predicate (wired into CapabilityRegistry).
        Denials leave a trust engram so trust is earned AND spent visibly."""
        domain = capability.name.split(".", 1)[0]
        allowed = self.level_for(agent_id, domain=domain) >= capability.autonomy_level
        if not allowed and self.store is not None:
            self.store.append(
                "trust",
                f"denial:{capability.name}",
                json.dumps(
                    {
                        "capability": capability.name,
                        "required_level": capability.autonomy_level,
                        "agent_level": self.level_for(agent_id, domain=domain),
                    }
                ),
                provenance={"system": "bene.kernel.harness.autonomy"},
                agent_id=agent_id,
                metadata={"signal": "denial"},
            )
        return allowed

    def guard(self, capability: Capability) -> Callable:
        """Decorator enforcing the ladder on any callable taking agent_id first."""

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(fn)
            def wrapper(agent_id: str, *args: Any, **kwargs: Any) -> Any:
                if not self.check(agent_id, capability):
                    raise AutonomyDenied(
                        f"agent {agent_id} denied {capability.name!r}"
                        f" (requires L{capability.autonomy_level})"
                    )
                return fn(agent_id, *args, **kwargs)

            return wrapper

        return deco
