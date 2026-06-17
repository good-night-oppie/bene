"""Continual Harness — probe-gated in-episode genome mutation.

Today ``ReflectiveEvolver.run()`` mutates strategy only BETWEEN generations,
outside any live agent loop. ``ContinualMutator`` lets a long-horizon agent swap
*one* component of its active genome mid-episode — but only behind the same kill
gate: a registered, hash-locked probe must ACCEPT (child beats parent on a
replay window) before the swap is persisted through ``promote()``'s front door
and the agent's active-genome pointer advances. REJECT/VOID hold the genome.

Scope (per the §7 adversarial split-scope verdict): this module is the
*mechanism* — budgets, probe gate, ``promote()`` front door, ``continual_swaps``
audit, autonomy L3 capability, and the active-genome pointer. The invasive
runner auto-trigger wiring (loop-guard / pollution → ``maybe_mutate`` each turn)
and a runner↔Genome binding are deliberately deferred; a caller (the CLI, a
test, or a future opted-in runner) drives ``maybe_mutate`` directly. Default
swappable components are the pure per-turn policy knobs (``context_strategy``,
``retrieval_policy``); stateful components (``prompt``, ``tool_config``,
``memory_policy``) require an explicit ``allowed_components`` override.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

import ulid

from bene.kernel.capabilities import Capability
from bene.kernel.engrams import EngramStore
from bene.kernel.eval import ACCEPT, VOID
from bene.kernel.eval.probe import Probe, ProbeNotRegistered
from bene.kernel.evolve.gepa import Genome, promote

IN_EPISODE_SWAP = Capability(
    name="evolve.in_episode_swap",
    description="hot-swap one genome component mid-episode after an ACCEPT verdict",
    autonomy_level=3,
    handler_ref=None,
    metadata={"continual": True},
)

SWAPPABLE_DEFAULT = ("context_strategy", "retrieval_policy")

CONTINUAL_SWAPS_DDL = """
CREATE TABLE IF NOT EXISTS continual_swaps (
    swap_id                 TEXT PRIMARY KEY,
    agent_id                TEXT NOT NULL,
    episode_id              TEXT NOT NULL,
    turn                    INTEGER NOT NULL DEFAULT 0,
    trigger_reason          TEXT NOT NULL,
    trigger_engram_id       TEXT,
    parent_genome_engram_id TEXT,
    child_genome_engram_id  TEXT NOT NULL,
    component               TEXT NOT NULL,
    verdict_engram_id       TEXT NOT NULL,
    swap_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_continual_swaps_agent
    ON continual_swaps(agent_id, episode_id, swap_at);
"""

# Decision statuses
SKIPPED, REJECTED, ACCEPTED_SWAPPED = "SKIPPED", "REJECTED", "ACCEPTED_SWAPPED"

ReflectFn = Callable[[Genome, dict], dict]
ReplayEvaluator = Callable[[Genome, list], dict]


@dataclass(frozen=True)
class SwapDecision:
    status: str  # SKIPPED | VOID | REJECTED | ACCEPTED_SWAPPED
    reason: str
    component: str | None = None
    child_engram_id: str | None = None
    verdict_engram: str | None = None
    swap_id: str | None = None

    @property
    def swapped(self) -> bool:
        return self.status == ACCEPTED_SWAPPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "component": self.component,
            "child_engram_id": self.child_engram_id,
            "verdict_engram": self.verdict_engram,
            "swap_id": self.swap_id,
        }


class ContinualMutator:
    CAPABILITY = IN_EPISODE_SWAP

    def __init__(
        self,
        store: EngramStore,
        conn: sqlite3.Connection,
        *,
        reflect_fn: ReflectFn,
        replay_evaluator: ReplayEvaluator,
        autonomy: Any = None,
        min_turns_between_swaps: int = 50,
        max_swaps_per_episode: int = 4,
        allowed_components: tuple[str, ...] = SWAPPABLE_DEFAULT,
    ) -> None:
        self.store = store
        self.conn = conn
        self.reflect_fn = reflect_fn
        self.replay_evaluator = replay_evaluator
        self.autonomy = autonomy
        self.min_turns_between_swaps = min_turns_between_swaps
        self.max_swaps_per_episode = max_swaps_per_episode
        self.allowed_components = tuple(allowed_components)
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.conn.executescript(CONTINUAL_SWAPS_DDL)

    # ---------------- read surface ----------------

    def swap_history(self, agent_id: str, *, episode_id: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT swap_id, episode_id, turn, trigger_reason, parent_genome_engram_id,"
            " child_genome_engram_id, component, verdict_engram_id, swap_at"
            " FROM continual_swaps WHERE agent_id=?"
        )
        params: list[Any] = [agent_id]
        if episode_id is not None:
            sql += " AND episode_id=?"
            params.append(episode_id)
        sql += " ORDER BY swap_at ASC, swap_id ASC"
        cols = [
            "swap_id",
            "episode_id",
            "turn",
            "trigger_reason",
            "parent_genome_engram_id",
            "child_genome_engram_id",
            "component",
            "verdict_engram_id",
            "swap_at",
        ]
        return [dict(zip(cols, r)) for r in self.conn.execute(sql, params).fetchall()]

    def active_genome_engram_id(self, agent_id: str, *, episode_id: str = "default") -> str | None:
        """The latest swapped-in child genome engram for this episode, or None
        if no swap has been accepted (caller falls back to its seed genome)."""
        row = self.conn.execute(
            "SELECT child_genome_engram_id FROM continual_swaps"
            " WHERE agent_id=? AND episode_id=? ORDER BY swap_at DESC, swap_id DESC LIMIT 1",
            (agent_id, episode_id),
        ).fetchone()
        return row[0] if row else None

    # ---------------- the gated swap ----------------

    def maybe_mutate(
        self,
        agent_id: str,
        active_genome: Genome,
        trigger: dict,
        *,
        probe: Probe,
        episode_id: str = "default",
        turn: int = 0,
    ) -> SwapDecision:
        rows = self.swap_history(agent_id, episode_id=episode_id)
        if len(rows) >= self.max_swaps_per_episode:
            return SwapDecision(SKIPPED, "max_swaps_per_episode reached")
        if rows and turn - int(rows[-1]["turn"]) < self.min_turns_between_swaps:
            return SwapDecision(SKIPPED, "min_turns_between_swaps not elapsed")

        window = trigger.get("replay_window_ids", [])
        baseline_scores = self.replay_evaluator(active_genome, window)
        proposal = self.reflect_fn(active_genome, {"trigger": trigger, "baseline": baseline_scores})
        component = proposal.get("component")
        if component not in self.allowed_components:
            return SwapDecision(SKIPPED, f"component {component!r} not in allowed_components")

        child = active_genome.mutate(component, proposal["new_text"])
        subject_scores = self.replay_evaluator(child, window)
        try:
            verdict = probe.run(subject_scores, baseline_scores, store=self.store, conn=self.conn)
        except ProbeNotRegistered:
            return SwapDecision(SKIPPED, "no registered probe for continual swap")

        if verdict.status != ACCEPT:
            self._record_rejected(agent_id, trigger, component, verdict)
            status = "VOID" if verdict.status == VOID else REJECTED
            return SwapDecision(
                status,
                f"probe returned {verdict.status}",
                component=component,
                verdict_engram=verdict.engram_id,
            )

        # ACCEPT → autonomy L3 gate (denials log a trust engram via check()).
        if self.autonomy is not None and not self.autonomy.check(agent_id, self.CAPABILITY):
            return SwapDecision(SKIPPED, "autonomy denied (evolve.in_episode_swap requires L3)")

        return self._commit_swap(
            agent_id, active_genome, child, component, verdict, trigger, episode_id, turn
        )

    def _commit_swap(
        self, agent_id, active_genome, child, component, verdict, trigger, episode_id, turn
    ):
        parent_engram = active_genome.engram_id
        child_engram = self.store.append(
            "strategic",
            f"continual-swap:{agent_id}:{component}",
            child.encode(),
            tier=4,
            provenance={"agent_id": agent_id},
            agent_id=agent_id,
            parents=[parent_engram] if parent_engram else None,
            link_type="derived_from",
            metadata={
                "continual": True,
                "component": component,
                "trigger": trigger.get("reason"),
                "trigger_engram_id": trigger.get("intervention_engram_id"),
            },
        )
        # Link the ACCEPT verdict verifies→child so promote()'s front door fires.
        self.store.link(verdict.engram_id, child_engram, "verifies")
        promote(
            child_engram, store=self.store, conn=self.conn
        )  # records gated_by, raises if no ACCEPT

        swap_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO continual_swaps (swap_id, agent_id, episode_id, turn, trigger_reason,"
            " trigger_engram_id, parent_genome_engram_id, child_genome_engram_id, component,"
            " verdict_engram_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                swap_id,
                agent_id,
                episode_id,
                turn,
                trigger.get("reason", "manual"),
                trigger.get("intervention_engram_id"),
                parent_engram,
                child_engram,
                component,
                verdict.engram_id,
            ),
        )
        self.conn.commit()
        return SwapDecision(
            ACCEPTED_SWAPPED,
            "swapped behind ACCEPT verdict",
            component=component,
            child_engram_id=child_engram,
            verdict_engram=verdict.engram_id,
            swap_id=swap_id,
        )

    def _record_rejected(self, agent_id, trigger, component, verdict) -> None:
        self.store.append(
            "intervention",
            f"continual-rejected:{agent_id}:{component}",
            json.dumps({"component": component, "verdict": verdict.status}),
            provenance={"system": "bene.kernel.evolve.continual"},
            agent_id=agent_id,
            metadata={
                "continual": True,
                "rejected_swap": True,
                "component": component,
                "verdict": verdict.status,
                "trigger": trigger.get("reason"),
            },
        )
        self.conn.commit()
