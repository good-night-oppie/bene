"""evolve_battle_harness — Contract-4 entrypoint for Lane B.

Drives bene MetaHarnessSearch-compatible evolution over the BattleHarness
genome (Contract-1) using a pluggable fitness_fn (Contract-3).

Build against mock_fitness until Lane A3 lands:

    from bene.kernel.battle import evolve_battle_harness, seed_harness, mock_fitness
    out = evolve_battle_harness(seed_harness(), mock_fitness, n_gen=2, run_seed=42)
    print(out.killgate_report)   # {"verdict": "ACCEPT", ...}

When Lane A3 is ready, swap mock_fitness for the real multi_dim_fitness fn:

    from adx_showdown.fitness import multi_dim_fitness
    out = evolve_battle_harness(seed_harness(), multi_dim_fitness, n_gen=5, run_seed=0)

Algorithm:
  1. Evaluate seed → baseline FitnessVector
  2. Register hash-locked kill-gate against seed
  3. For each generation:
     a. Mutate current best → *candidates_per_gen* children
     b. Evaluate children via fitness_fn
     c. Update Pareto frontier (Contract-3 dimensions, all maximised)
     d. Promote new best (max win_rate) if it improves on current
  4. Run kill-gate on best: ACCEPT iff win_rate_uplift≥0.10 AND
     battles_played>0 AND gens_completed>0
  5. Write SharedLog lineage entry to fleet bus
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

import ulid

from bene.kernel.battle.genome import (
    BattleHarness,
    CONTRACT3_OBJECTIVES,
    FitnessVector,
)
from bene.kernel.battle.killgate import build_killgate, open_eval_db
from bene.kernel.battle.lineage import write_lineage
from bene.kernel.engrams import EngramStore
from bene.kernel.eval.gates import lock_hash
from bene.kernel.eval.probe import LockTamperError, Probe
from bene.metaharness.harness import EvaluationResult
from bene.metaharness.pareto import ParetoFrontier, compute_pareto

FitnessFn = Callable[[BattleHarness], FitnessVector]


@dataclass
class GenerationLog:
    gen: int
    candidates: list[dict[str, Any]]
    pareto_ids: list[str]
    best_harness_id: str
    best_scores: dict[str, float]


@dataclass
class EvolveOutput:
    """Contract-4 return value."""

    best: BattleHarness
    lineage: list[GenerationLog]
    killgate_report: dict[str, Any]
    pareto: ParetoFrontier


def evolve_battle_harness(
    seed: BattleHarness,
    fitness_fn: FitnessFn,
    n_gen: int = 1,
    run_seed: int = 0,
    candidates_per_gen: int = 3,
    db_path: str | None = None,
    bus_path: str | None = None,
) -> EvolveOutput:
    """Evolve *seed* for *n_gen* generations and return the best harness.

    Args:
        seed:               H0 genome (Contract-1).
        fitness_fn:         maps BattleHarness → FitnessVector (Contract-3).
                            Use mock_fitness until Lane A3 lands.
        n_gen:              number of evolution generations (≥1).
        run_seed:           RNG seed for reproducibility.
        candidates_per_gen: children to produce each generation.
        db_path:            bene.db path for kill-gate persistence; None →
                            in-memory (fine for mock/test runs).
        bus_path:           A2A fleet bus path; None → default.
    """
    if n_gen < 1:
        raise ValueError("n_gen must be ≥1")

    run_id = str(ulid.new())
    rng = random.Random(run_seed)
    store, conn = open_eval_db(db_path)

    # ------------------------------------------------------------------
    # Evaluate seed (baseline)
    seed_fv = fitness_fn(seed)

    # ------------------------------------------------------------------
    # Persist the seed as a candidate engram so the kill-gate verdict links
    # verifies/refutes → a *real* engram (not a dangling harness_id string).
    # promote()/trust queries key off the candidate ENGRAM id, so without this
    # an ACCEPT verdict could never gate the candidate through the kernel.
    seed_eid = _append_harness_engram(store, seed)

    # ------------------------------------------------------------------
    # Register kill-gate against the seed baseline (gens_completed=0).
    # The identity self-test runs internally: seed vs seed → win_rate_uplift=0
    # → gate kills → probe is admissible.
    #
    # Idempotent against a persistent DB (probe_registry.name is UNIQUE): a 2nd
    # evolve run on the same db_path REUSES the already-registered same-name
    # probe instead of blind-INSERTing (which would raise IntegrityError and
    # abort before evolution completes). The gate spec is fixed + hash-locked,
    # so a mismatched stored lock is treated as tamper.
    probe = build_killgate()
    _ensure_probe(
        probe, store, conn, baseline=seed_fv.replace(gens_completed=0), subject_ref=seed_eid
    )

    # ------------------------------------------------------------------
    # Evolution loop
    all_results: list[EvaluationResult] = [_to_eval_result(seed, seed_fv)]
    all_harnesses: dict[str, BattleHarness] = {seed.harness_id: seed}
    lineage: list[GenerationLog] = []
    best_harness = seed
    best_fv = seed_fv

    for gen in range(n_gen):
        gen_candidates: list[dict[str, Any]] = []
        # Capture the generation-start parent BEFORE any in-generation promotion:
        # every mutant in this batch is a child of this parent, even siblings
        # evaluated after an earlier sibling promotes best_harness. Reading
        # best_harness.harness_id inside the loop would mis-record a promoted
        # sibling as the parent of its own batch-mates and corrupt the lineage.
        gen_parent_id = best_harness.harness_id
        mutants = [best_harness.mutate(rng) for _ in range(candidates_per_gen)]

        for mutant in mutants:
            fv = fitness_fn(mutant)
            all_results.append(_to_eval_result(mutant, fv))
            all_harnesses[mutant.harness_id] = mutant
            gen_candidates.append(
                {
                    "harness_id": mutant.harness_id,
                    "parent_id": gen_parent_id,
                    "scores": fv.to_scores(),
                }
            )
            # Promote if win_rate improves (greedy single-objective selection
            # for the current best; Pareto frontier tracks full tradeoffs)
            if fv.win_rate > best_fv.win_rate:
                best_harness, best_fv = mutant, fv

        pareto = compute_pareto(all_results, CONTRACT3_OBJECTIVES)
        lineage.append(
            GenerationLog(
                gen=gen + 1,
                candidates=gen_candidates,
                pareto_ids=[p.harness_id for p in pareto.points],
                best_harness_id=best_harness.harness_id,
                best_scores=best_fv.to_scores(),
            )
        )

    # ------------------------------------------------------------------
    # Final Pareto frontier over all evaluated harnesses
    final_pareto = compute_pareto(all_results, CONTRACT3_OBJECTIVES)

    # ------------------------------------------------------------------
    # Kill-gate: stamp gens_completed, run probe.
    # Reuse the cached best_fv that drove Pareto/lineage selection — do NOT
    # re-evaluate via fitness_fn. With a noisy/side-effectful fitness_fn (real
    # battle sampling) a fresh call would gate on scores that were never part
    # of the recorded candidate evaluation, so frontier/lineage and the gate
    # evidence would diverge.
    best_fv_final = best_fv.replace(gens_completed=n_gen)
    seed_fv_baseline = seed_fv.replace(gens_completed=0)

    # Persist the evolved best as a candidate engram so the verdict's verifies/
    # refutes edge points at a real engram and promote(best_eid) can consume it.
    best_eid = (
        seed_eid
        if best_harness.harness_id == seed.harness_id
        else _append_harness_engram(store, best_harness, parents=[seed_eid])
    )

    verdict = probe.run(
        subject=best_fv_final,
        baseline=seed_fv_baseline,
        store=store,
        conn=conn,
        subject_ref=best_eid,
    )

    killgate_report: dict[str, Any] = {
        "verdict": verdict.status,
        "probe": verdict.probe_name,
        "killed_gates": verdict.killed_gates,
        "gate_results": verdict.gate_results,
        "best_harness_id": best_harness.harness_id,
        "seed_harness_id": seed.harness_id,
        "best_engram_id": best_eid,
        "seed_engram_id": seed_eid,
        "seed_win_rate": seed_fv.win_rate,
        "best_win_rate": best_fv_final.win_rate,
        "uplift": best_fv_final.win_rate - seed_fv.win_rate,
        "gens_completed": n_gen,
        "battles_played": best_fv_final.battles_played,
    }

    # ------------------------------------------------------------------
    # SharedLog lineage (best-effort; non-fatal on bus failure)
    if bus_path is not False:
        write_lineage(
            run_id=run_id,
            payload={
                "run_id": run_id,
                "run_seed": run_seed,
                "n_gen": n_gen,
                "verdict": verdict.status,
                "uplift": killgate_report["uplift"],
                "best_harness_id": best_harness.harness_id,
                "lineage_len": len(lineage),
            },
            **({"bus_path": bus_path} if bus_path is not None else {}),
        )

    return EvolveOutput(
        best=best_harness,
        lineage=lineage,
        killgate_report=killgate_report,
        pareto=final_pareto,
    )


# ---------------------------------------------------------------------------
# Helpers


def _to_eval_result(harness: BattleHarness, fv: FitnessVector) -> EvaluationResult:
    return EvaluationResult(
        harness_id=harness.harness_id,
        scores=fv.to_scores(),
    )


def _append_harness_engram(
    store: EngramStore,
    harness: BattleHarness,
    parents: list[str] | None = None,
) -> str:
    """Persist a BattleHarness as a strategic candidate engram and return its id.

    Genomes/genes live at the ``strategic`` tier (tier 4) across the ladder —
    ReflectiveEvolver, the metaharness bridge, and the sibling codex_harness lane
    all persist candidates that way — so a battle candidate must too, else
    strategic-genome surfaces miss it even though the verdict links to it. (PR #82 review)

    The kill-gate verdict links verifies/refutes → this engram id, so the
    candidate can later be gated through the kernel promotion front door
    (promote() / trust queries key off the candidate engram id, not the raw
    harness_id string). The human-readable harness_id is kept in metadata.
    """
    return store.append(
        "strategic",
        f"battle-harness:{harness.harness_id}",
        harness.to_json(),
        provenance={"system": "bene.kernel.battle"},
        parents=parents,
        tier=4,
        metadata={"harness_id": harness.harness_id},
    )


def _ensure_probe(
    probe: Probe,
    store: EngramStore,
    conn: sqlite3.Connection,
    *,
    baseline: FitnessVector,
    subject_ref: str | None = None,
) -> None:
    """Register the kill-gate probe idempotently (register-or-reuse).

    probe_registry.name is UNIQUE, so a blind re-register on a persistent DB (a
    2nd evolve run on the same db_path, a process restart) would raise
    IntegrityError and abort the run. Mirrors codex_harness/continual._ensure_probe:
    reuse an already-registered same-name row if present; on a lost race, re-select;
    treat a mismatched stored lock as tamper.
    """
    existing = conn.execute(
        "SELECT lock_sha256 FROM probe_registry WHERE name=?", (probe.name,)
    ).fetchone()
    if existing is None:
        try:
            probe.register(store, conn, baseline=baseline, subject_ref=subject_ref)
            return
        except sqlite3.IntegrityError:
            # Lost a race to a concurrent registrant — reuse its row below.
            existing = conn.execute(
                "SELECT lock_sha256 FROM probe_registry WHERE name=?", (probe.name,)
            ).fetchone()
    if existing is not None and existing[0] != lock_hash(probe.gates):
        raise LockTamperError(
            f"probe {probe.name}: an existing registration's lock differs from "
            "the in-memory gate spec"
        )
