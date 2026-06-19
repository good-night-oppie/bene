"""Continual-Harness pillar (SECH B3, bene-core) — in-episode hot-swap of a CodexHarness.

``evolve_codex_harness`` (B1) freezes the harness for a full arena eval and only advances
the incumbent BETWEEN generations. The **Continual-Harness** pillar (arXiv 2605.09998)
lets a long-horizon episode adapt its harness *within* the episode: when the active
harness is failing mid-run, the Refiner proposes a fix and the agent's active-harness
pointer **hot-swaps** to it — but only behind the same falsifiable safety machinery:

  * **gated** — the swapped-in child must beat the incumbent on a *replay window* by
    ``>=CONTINUAL_MIN_UPLIFT`` (the hash-locked, tamper-refusing continual kill-gate);
    a non-improving child is REJECTED and the incumbent holds (in-episode rollback).
  * **bounded** — a per-episode swap *budget* + a *cooldown* (min turns between swaps)
    stop thrash (an agent that swaps every turn learns nothing).
  * **safe** — a proposal that does not build (Contract-S reject) is never swapped to
    (``apply_fn -> None`` / raise == rollback), so the live agent never runs an
    unbuildable harness.
  * **audited** — every accepted swap is appended to ``codex_continual_swaps`` with the
    from/to harness + the mutation + the verdict, so the in-episode genealogy is provable.
  * **L3-gated** — the swap is an autonomy-L3 capability; an L4 grant is never required
    and never bypassed.

bene owns the **control loop** (budgets, gate, swap pointer, audit, the falsifiable
*continual-beats-static* property). adx swaps in the real arena replay-eval (Contract E
over a window), the Refiner (Contract R), and the sandbox apply/validate (Contract S) —
the same callable signatures ``evolve_codex_harness`` already takes. Mock-first, like B1::

    from bene.kernel.codex_harness import (
        run_continual_episode, seed_codex_harness, mock_refiner, mock_replay_eval,
    )
    out = run_continual_episode(
        seed_codex_harness(), mock_refiner, mock_replay_eval, run_seed=7, bus_path=False,
    )
    out.n_swaps                      # >= 1 (the failing seed was hot-swapped)
    out.continual_uplift_vs_static   # > 0 (continual adaptation beat the static seed)
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import ulid

from bene.kernel.capabilities import Capability
from bene.kernel.codex_harness.genome import (
    CodexEvalResult,
    CodexFitness,
    CodexHarness,
    Mutation,
    mock_apply,
)
from bene.kernel.codex_harness.killgate import build_continual_killgate, open_eval_db
from bene.kernel.codex_harness.lineage import write_lineage
from bene.kernel.eval import ACCEPT, VOID
from bene.kernel.eval.gates import lock_hash
from bene.kernel.eval.probe import LockTamperError, Probe, ProbeNotRegistered

# The Refiner (Contract R) + sandbox apply (Contract S) + replay-window eval (Contract E,
# scoped to the in-episode window) — identical signatures to evolve_codex_harness so adx
# drives the continual loop with the same operators it drives the generational loop with.
RefineFn = Callable[[CodexHarness, dict[str, Any], list[str]], list[Mutation]]
ApplyFn = Callable[[CodexHarness, Mutation], "CodexHarness | None"]
ReplayEvalFn = Callable[[CodexHarness, int, int], CodexEvalResult]

# In-episode hot-swap is an autonomy-L3 capability (mid-run self-modification). L4 stays
# human-only and is never required nor bypassed here (the SECH/landing hard contract).
CODEX_IN_EPISODE_SWAP = Capability(
    name="codex_harness.in_episode_swap",
    description="hot-swap the active CodexHarness mid-episode after an ACCEPT verdict",
    autonomy_level=3,
    handler_ref=None,
    metadata={"continual": True, "pillar": "continual_harness"},
)

# Swap-decision statuses.
SKIPPED = "SKIPPED"  # budget / cooldown / no buildable candidate — incumbent holds
REJECTED = "REJECTED"  # a built child that did not clear the gate — incumbent holds
VOIDED = "VOID"  # inadmissible (empty replay window / probe inadmissible)
ACCEPTED_SWAPPED = "ACCEPTED_SWAPPED"  # active-harness pointer advanced to the child

CONTINUAL_SWAPS_DDL = """
CREATE TABLE IF NOT EXISTS codex_continual_swaps (
    swap_id          TEXT PRIMARY KEY,
    episode_id       TEXT NOT NULL,
    turn             INTEGER NOT NULL DEFAULT 0,
    trigger_reason   TEXT NOT NULL,
    from_harness_id  TEXT NOT NULL,
    to_harness_id    TEXT NOT NULL,
    mutation_kind    TEXT NOT NULL,
    target_path      TEXT,
    verdict          TEXT NOT NULL,
    uplift           REAL NOT NULL,
    swap_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_codex_continual_swaps_ep
    ON codex_continual_swaps(episode_id);
"""

_SWAP_COLS = (
    "swap_id",
    "episode_id",
    "turn",
    "trigger_reason",
    "from_harness_id",
    "to_harness_id",
    "mutation_kind",
    "target_path",
    "verdict",
    "uplift",
    "swap_at",
)


@dataclass
class CodexSwapDecision:
    """The outcome of one ``maybe_swap`` attempt."""

    status: str  # SKIPPED | REJECTED | VOID | ACCEPTED_SWAPPED
    reason: str
    new_harness: CodexHarness | None = None  # swapped-in active harness (ACCEPTED only)
    mutation_kind: str | None = None
    target_path: str | None = None
    uplift: float = 0.0
    verdict: str | None = None
    rollbacks: int = 0  # proposals that did not build (Contract-S reject) this attempt
    swap_id: str | None = None

    @property
    def swapped(self) -> bool:
        return self.status == ACCEPTED_SWAPPED

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["new_harness_id"] = self.new_harness.harness_id if self.new_harness else None
        d.pop("new_harness", None)
        return d


class ContinualCodexMutator:
    """Probe-gated, budget-bounded in-episode hot-swap of a CodexHarness (B3 mechanism).

    Self-contained on the codex-harness genome (no dependency on the GEPA ``evolve``
    package nor ``bene.kernel.battle``), mirroring ``codex_harness.killgate``. The caller
    (a runner, the driver below, or a test) drives ``maybe_swap`` on a trigger; the
    invasive per-turn auto-trigger wiring is the runner's, deferred exactly as the GEPA
    ``ContinualMutator`` defers it.
    """

    CAPABILITY = CODEX_IN_EPISODE_SWAP

    def __init__(
        self,
        store: Any,
        conn: sqlite3.Connection,
        *,
        refine_fn: RefineFn,
        replay_eval_fn: ReplayEvalFn,
        apply_fn: ApplyFn = mock_apply,
        probe: Probe | None = None,
        autonomy: Any = None,
        agent_id: str = "codex-episode",
        replay_window: int = 20,
        max_swaps_per_episode: int = 4,
        min_turns_between_swaps: int = 50,
        candidates_per_swap: int = 4,
    ) -> None:
        self.store = store
        self.conn = conn
        self.refine_fn = refine_fn
        self.replay_eval_fn = replay_eval_fn
        self.apply_fn = apply_fn
        self.probe = probe or build_continual_killgate()
        self.autonomy = autonomy
        self.agent_id = agent_id
        self.replay_window = replay_window
        self.max_swaps_per_episode = max_swaps_per_episode
        self.min_turns_between_swaps = min_turns_between_swaps
        self.candidates_per_swap = candidates_per_swap
        self._registered = False
        self.conn.executescript(CONTINUAL_SWAPS_DDL)

    # ---------------- read surface ----------------

    def swap_history(self, episode_id: str) -> list[dict[str, Any]]:
        """Accepted swaps for *episode_id*, in insertion order (rowid)."""
        sql = (
            f"SELECT {', '.join(_SWAP_COLS)} FROM codex_continual_swaps"
            " WHERE episode_id=? ORDER BY rowid ASC"
        )
        return [dict(zip(_SWAP_COLS, r)) for r in self.conn.execute(sql, (episode_id,)).fetchall()]

    def active_harness_id(self, episode_id: str) -> str | None:
        """The latest swapped-in harness id for *episode_id*, or None (use the seed)."""
        row = self.conn.execute(
            "SELECT to_harness_id FROM codex_continual_swaps"
            " WHERE episode_id=? ORDER BY rowid DESC LIMIT 1",
            (episode_id,),
        ).fetchone()
        return row[0] if row else None

    # ---------------- the gated swap ----------------

    def maybe_swap(
        self,
        episode_id: str,
        active_harness: CodexHarness,
        trigger: dict[str, Any],
        *,
        run_seed: int = 0,
        turn: int = 0,
        baseline_eval: CodexEvalResult | None = None,
    ) -> CodexSwapDecision:
        """Attempt one in-episode hot-swap of *active_harness*; return the decision.

        ``trigger`` carries ``{reason, replay_window?, failure_signatures?, trajectory?}``.
        When ``failure_signatures`` is absent it is derived by replay-evaluating the
        incumbent (so a caller can pass a bare ``{"reason": ...}``). A caller that already
        replay-evaluated the incumbent (e.g. the driver, to read its trigger signals) may
        pass ``baseline_eval=`` to avoid a second Contract-E eval (it can be expensive).
        """
        window = int(trigger.get("replay_window", self.replay_window))
        if window <= 0:
            # An empty replay window can prove nothing about a swap — inadmissible,
            # never a silent pass (mirrors the generational empty-manifest VOID).
            return CodexSwapDecision(VOIDED, "empty_replay_window")

        rows = self.swap_history(episode_id)
        if len(rows) >= self.max_swaps_per_episode:
            return CodexSwapDecision(SKIPPED, "max_swaps_per_episode reached")
        if rows and turn - int(rows[-1]["turn"]) < self.min_turns_between_swaps:
            return CodexSwapDecision(SKIPPED, "min_turns_between_swaps not elapsed")

        # Baseline = the incumbent on the replay window. Registration (lazy, once) uses
        # this for the admissibility self-test; the gate run uses it as the live baseline.
        # Reuse a caller-supplied eval over the same window rather than running it twice.
        if baseline_eval is None:
            baseline_eval = self.replay_eval_fn(active_harness, run_seed, window)
        baseline_fv = baseline_eval.fitness
        # Anti-vacuous: the incumbent's replay window must have OBSERVED battles. An arena
        # timeout / empty replay yields battles_played==0, and the CONTINUAL_GATES
        # anti-vacuous gate only checks the CHILD — so a child with games + uplift would
        # ACCEPT against an unobserved baseline, making the hot-swap vacuous. VOID before
        # registering/running the gate (an inadmissible comparison, not a REJECT). (PR #71 review)
        if baseline_fv.battles_played <= 0:
            return CodexSwapDecision(
                VOIDED, "incumbent replay window reported 0 observed battles (vacuous baseline)"
            )
        self._ensure_probe(active_harness, baseline_fv)

        failure_sigs = trigger.get("failure_signatures")
        if failure_sigs is None:
            failure_sigs = baseline_eval.failure_signatures
        trajectory = trigger.get("trajectory") or baseline_eval.trajectory

        # PROPOSE — the Refiner reads the incumbent's trajectory + failures (NOT random).
        mutations = self.refine_fn(active_harness, trajectory, list(failure_sigs))
        if not mutations:
            return CodexSwapDecision(SKIPPED, "refiner proposed no mutation")

        # ASSESS — apply+validate each candidate; keep the best buildable child on the
        # SAME replay window. An unbuildable proposal is a rollback, never a crash.
        best: tuple[CodexHarness, CodexFitness, Mutation] | None = None
        rollbacks = 0
        evaluated = 0
        for mutation in mutations:
            if evaluated >= self.candidates_per_swap:
                break
            try:
                child = self.apply_fn(active_harness, mutation)
            except Exception:  # noqa: BLE001 — any Contract-S apply failure is a rollback
                child = None
            if child is None:
                rollbacks += 1
                continue
            child_fv = self.replay_eval_fn(child, run_seed, window).fitness
            evaluated += 1
            if best is None or child_fv.win_rate > best[1].win_rate:
                best = (child, child_fv, mutation)

        if best is None:
            return CodexSwapDecision(
                SKIPPED,
                "no buildable candidate (all proposals rolled back)",
                rollbacks=rollbacks,
            )
        child, child_fv, mutation = best
        uplift = child_fv.win_rate - baseline_fv.win_rate

        # GATE — the hash-locked continual kill-gate: child must beat the incumbent on
        # the replay window by >=CONTINUAL_MIN_UPLIFT (anti-vacuous: window observed >0).
        try:
            verdict = self.probe.run(
                subject=child_fv,
                baseline=baseline_fv,
                store=self.store,
                conn=self.conn,
                subject_ref=child.harness_id,
            )
        except ProbeNotRegistered:
            return CodexSwapDecision(SKIPPED, "no registered probe for continual swap")

        if verdict.status != ACCEPT:
            status = VOIDED if verdict.status == VOID else REJECTED
            return CodexSwapDecision(
                status,
                f"gate returned {verdict.status}",
                mutation_kind=mutation.kind,
                target_path=mutation.target_path,
                uplift=uplift,
                verdict=verdict.status,
                rollbacks=rollbacks,
            )

        # ACCEPT -> autonomy L3 gate (a denial logs a trust engram via check()).
        if self.autonomy is not None and not self.autonomy.check(self.agent_id, self.CAPABILITY):
            return CodexSwapDecision(
                SKIPPED,
                "autonomy denied (codex_harness.in_episode_swap requires L3)",
                mutation_kind=mutation.kind,
                target_path=mutation.target_path,
                uplift=uplift,
                verdict=verdict.status,
                rollbacks=rollbacks,
            )

        # COMMIT — advance the active-harness pointer + audit the swap.
        swap_id = self._record_swap(
            episode_id, turn, trigger, active_harness, child, mutation, verdict.status, uplift
        )
        return CodexSwapDecision(
            ACCEPTED_SWAPPED,
            "hot-swapped behind ACCEPT verdict",
            new_harness=child,
            mutation_kind=mutation.kind,
            target_path=mutation.target_path,
            uplift=uplift,
            verdict=verdict.status,
            rollbacks=rollbacks,
            swap_id=swap_id,
        )

    # ---------------- internals ----------------

    def _ensure_probe(self, baseline_harness: CodexHarness, baseline_fv: CodexFitness) -> None:
        if self._registered:
            return
        # Idempotent against a persistent DB / a second mutator on the same conn: the gate
        # spec is fixed + hash-locked, so an already-registered same-name probe is REUSED
        # rather than re-INSERTed. probe_registry.name is UNIQUE, so a blind re-register
        # (a 2nd episode, a re-instantiated runner, a process restart) would otherwise
        # raise IntegrityError and abort the episode before any swap is evaluated.
        existing = self.conn.execute(
            "SELECT lock_sha256 FROM probe_registry WHERE name=?", (self.probe.name,)
        ).fetchone()
        if existing is None:
            try:
                self.probe.register(
                    self.store,
                    self.conn,
                    baseline=baseline_fv,
                    subject_ref=baseline_harness.harness_id,
                )
                self._registered = True
                return
            except sqlite3.IntegrityError:
                # Lost a race to a concurrent registrant — reuse its row below.
                existing = self.conn.execute(
                    "SELECT lock_sha256 FROM probe_registry WHERE name=?", (self.probe.name,)
                ).fetchone()
        if existing is not None and existing[0] != lock_hash(self.probe.gates):
            raise LockTamperError(
                f"probe {self.probe.name}: an existing registration's lock differs from "
                "the in-memory gate spec"
            )
        self._registered = True

    def _record_swap(
        self,
        episode_id: str,
        turn: int,
        trigger: dict[str, Any],
        parent: CodexHarness,
        child: CodexHarness,
        mutation: Mutation,
        verdict_status: str,
        uplift: float,
    ) -> str:
        swap_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO codex_continual_swaps (swap_id, episode_id, turn, trigger_reason,"
            " from_harness_id, to_harness_id, mutation_kind, target_path, verdict, uplift)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                swap_id,
                episode_id,
                turn,
                str(trigger.get("reason", "manual")),
                parent.harness_id,
                child.harness_id,
                mutation.kind,
                mutation.target_path,
                verdict_status,
                float(uplift),
            ),
        )
        self.conn.commit()
        return swap_id


# ---------------------------------------------------------------------------
# End-to-end driver — simulate an episode and return the falsifiable continual record.


@dataclass
class ContinualEpisodeOutput:
    """The result of a continual-harness episode (the B3 falsifiable-DONE surface)."""

    episode_id: str
    seed_harness: CodexHarness
    final_harness: CodexHarness
    swaps: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[CodexSwapDecision] = field(default_factory=list)
    n_swaps: int = 0
    n_rejected: int = 0
    n_rollbacks: int = 0
    final_win_rate: float = 0.0
    static_win_rate: float = 0.0
    continual_uplift_vs_static: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "seed_harness_id": self.seed_harness.harness_id,
            "final_harness_id": self.final_harness.harness_id,
            "swaps": self.swaps,
            "n_swaps": self.n_swaps,
            "n_rejected": self.n_rejected,
            "n_rollbacks": self.n_rollbacks,
            "final_win_rate": self.final_win_rate,
            "static_win_rate": self.static_win_rate,
            "continual_uplift_vs_static": self.continual_uplift_vs_static,
        }


def run_continual_episode(
    seed: CodexHarness,
    refine_fn: RefineFn,
    replay_eval_fn: ReplayEvalFn,
    *,
    apply_fn: ApplyFn = mock_apply,
    run_seed: int = 0,
    n_turns: int = 300,
    trigger_turns: list[int] | None = None,
    replay_window: int = 20,
    max_swaps_per_episode: int = 4,
    min_turns_between_swaps: int = 50,
    candidates_per_swap: int = 4,
    autonomy: Any = None,
    agent_id: str = "codex-episode",
    episode_id: str | None = None,
    db_path: str | None = None,
    bus_path: str | None = None,
) -> ContinualEpisodeOutput:
    """Drive a continual-harness episode: hot-swap the active harness whenever it is
    failing mid-run, behind the kill-gate + budget + cooldown, and return the record.

    A swap is *attempted* on each trigger turn for which the incumbent still has an
    addressable failure signature; the gate decides whether it lands. The falsifiable
    property is ``continual_uplift_vs_static`` >= 0 — the continually-adapted final
    harness is never worse than the static seed held fixed across the episode, and on a
    genuinely-failing seed it is strictly better.
    """
    store, conn = open_eval_db(db_path)
    episode_id = episode_id or str(ulid.new())
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=refine_fn,
        replay_eval_fn=replay_eval_fn,
        apply_fn=apply_fn,
        autonomy=autonomy,
        agent_id=agent_id,
        replay_window=replay_window,
        max_swaps_per_episode=max_swaps_per_episode,
        min_turns_between_swaps=min_turns_between_swaps,
        candidates_per_swap=candidates_per_swap,
    )

    if trigger_turns is None:
        step = max(1, min_turns_between_swaps)
        trigger_turns = list(range(0, max(1, n_turns), step))

    active = seed
    decisions: list[CodexSwapDecision] = []
    n_rejected = 0
    n_rollbacks = 0
    for turn in trigger_turns:
        ev = replay_eval_fn(active, run_seed, replay_window)
        if not ev.failure_signatures:
            continue  # incumbent healthy -> nothing to fix, no swap attempt
        trigger = {
            "reason": "in_episode_failure",
            "replay_window": replay_window,
            "failure_signatures": ev.failure_signatures,
            "trajectory": ev.trajectory,
        }
        # Pass the trigger eval as the baseline so maybe_swap does not re-run Contract-E.
        decision = mut.maybe_swap(
            episode_id, active, trigger, run_seed=run_seed, turn=turn, baseline_eval=ev
        )
        decisions.append(decision)
        n_rollbacks += decision.rollbacks
        if decision.swapped and decision.new_harness is not None:
            active = decision.new_harness
        elif decision.status == REJECTED:
            n_rejected += 1

    final_fv = replay_eval_fn(active, run_seed, replay_window).fitness
    static_fv = replay_eval_fn(seed, run_seed, replay_window).fitness
    swaps = mut.swap_history(episode_id)

    out = ContinualEpisodeOutput(
        episode_id=episode_id,
        seed_harness=seed,
        final_harness=active,
        swaps=swaps,
        decisions=decisions,
        n_swaps=len(swaps),
        n_rejected=n_rejected,
        n_rollbacks=n_rollbacks,
        final_win_rate=final_fv.win_rate,
        static_win_rate=static_fv.win_rate,
        continual_uplift_vs_static=final_fv.win_rate - static_fv.win_rate,
    )

    # SharedLog lineage (best-effort; non-fatal on bus failure) — reuse the codex
    # evolution lineage writer. write_lineage stamps kind='evolution' by default; the
    # payload's own kind overrides it so a continual hot-swap run is distinguishable from
    # a generational evolve on the bus.
    if bus_path is not False:
        write_lineage(
            run_id=episode_id,
            payload={
                "kind": "continual",
                "run_id": episode_id,
                "task": "codex-harness-continual",
                "run_seed": run_seed,
                "n_swaps": out.n_swaps,
                "continual_uplift_vs_static": out.continual_uplift_vs_static,
                "final_harness_id": active.harness_id,
            },
            **({"bus_path": bus_path} if bus_path is not None else {}),
        )

    return out


# ---------------------------------------------------------------------------
# Deterministic in-episode mock eval (no RNG) — the replay-window analog of
# ``mock_codex_eval``. Strength accumulates through applied code/tool mutations, so a
# failing seed climbs as the Refiner's swaps land; the failure signatures it emits are
# exactly the ones ``mock_refiner`` knows how to fix. Replace with adx's Contract-E
# replay-window eval (same signature).


def mock_replay_eval(harness: CodexHarness, run_seed: int = 0, window: int = 20) -> CodexEvalResult:
    strength = float(harness.params.get("_mock_strength", 0.0))
    win_rate = min(1.0, max(0.0, 0.50 + strength))
    legibility = min(1.0, max(0.0, 0.62 + strength))
    turn_eff = min(1.0, max(0.05, 0.72 + strength * 0.5))
    no_forfeit = min(1.0, max(0.0, 0.90))
    elo = 1000.0 + (win_rate - 0.5) * 800.0

    sigs: list[str] = []
    if win_rate < 0.60:
        sigs.append("loss_vs_baseline")
    if legibility < 0.70:
        sigs.append("illegal_move")
    if turn_eff < 0.80:
        sigs.append("stall")

    training_tuples = [["episode", int(run_seed), f"window{i}"] for i in range(3)]
    return CodexEvalResult(
        fitness=CodexFitness(
            win_rate=win_rate,
            elo=elo,
            move_legibility=legibility,
            no_forfeit_exploit=no_forfeit,
            turn_efficiency=turn_eff,
            battles_played=max(0, window),
            gens_completed=0,
        ),
        trajectory={"harness_id": harness.harness_id, "run_seed": run_seed, "window": window},
        failure_signatures=sigs,
        training_tuples=training_tuples,
    )
