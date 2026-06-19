"""evolve_codex_harness — SECH Contract G (bene-core B1).

The bene-core lane of the Self-Evolving Codex Harness work-order
(``tasks/codex-harness-evolution/SPEC.md``): bene MetaHarnessSearch with the
**Refiner** as the mutation operator (NOT a random mutate), the **arena** as the
fitness evaluator, the **hash-locked kill-gate** as the falsifiable promotion gate,
and the **DGM archive** keeping every accepted harness for open-ended search.

The loop (Darwin-Gödel / Autogenesis SEPL, gated by the arena):

    seed H0
      ACT      eval_fn(H)   -> fitness + trajectory                 (Contract E)
      OBSERVE  failure signatures from the trajectory
      PROPOSE  refine_fn(H, trajectory, signatures) -> [Mutation]   (Contract R)
      ASSESS   apply_fn(H, mutation) -> H' | None(reject) ; eval H'  (Contract S + E)
      GATE     keep H' iff it beats the incumbent (non-improving / unbuildable ->
               rollback); the final hash-locked kill-gate verdict is best-ever vs seed
      COMMIT   accepted H' -> DGM archive (open-ended) + lineage

B1 runs against ``mock_refiner`` / ``mock_apply`` / ``mock_codex_eval`` (sanctioned by
the SPEC sequencing). Swap them for adx-core's real Refiner (Contract R) + sandbox
apply/validate (Contract S) + adx's arena eval (Contract E) — same signatures.

Contract-G signature note: the SPEC lists ``evolve_codex_harness(H0, refine_fn,
eval_fn, n_gen, run_seed)``; the apply/validate step (Contract S) is folded in as an
injected ``apply_fn`` (mock default) so ASSESS is real, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import ulid

from bene.kernel.codex_harness.archive import DGMArchive
from bene.kernel.codex_harness.genome import (
    CodexEvalResult,
    CodexFitness,
    CodexHarness,
    Mutation,
    mock_apply,
)
from bene.kernel.codex_harness.heldout import HeldoutManifest, overlap
from bene.kernel.codex_harness.killgate import (
    KILLGATE_GATES,
    PROBE_NAME,
    build_killgate,
    open_eval_db,
)
from bene.kernel.codex_harness.lineage import write_lineage
from bene.kernel.eval import VOID
from bene.kernel.eval.gates import lock_hash

RefineFn = Callable[[CodexHarness, dict[str, Any], list[str]], list[Mutation]]
ApplyFn = Callable[[CodexHarness, Mutation], "CodexHarness | None"]
EvalFn = Callable[[CodexHarness, int, int], CodexEvalResult]


@dataclass
class GenerationLog:
    gen: int
    candidates: list[dict[str, Any]]
    incumbent_id: str
    incumbent_scores: dict[str, float]
    promoted: bool


@dataclass
class EvolveOutput:
    """Contract-G return value."""

    best: CodexHarness
    archive: DGMArchive
    lineage: list[GenerationLog] = field(default_factory=list)
    killgate_report: dict[str, Any] = field(default_factory=dict)


def evolve_codex_harness(
    seed: CodexHarness,
    refine_fn: RefineFn,
    eval_fn: EvalFn,
    n_gen: int = 1,
    run_seed: int = 0,
    *,
    apply_fn: ApplyFn = mock_apply,
    candidates_per_gen: int = 4,
    n_battles: int = 30,
    heldout_manifest: HeldoutManifest | None = None,
    db_path: str | None = None,
    bus_path: str | None = None,
) -> EvolveOutput:
    """Evolve *seed* for *n_gen* generations via the Refiner and return the best.

    Args:
        seed:               H0 codex harness (Contract H head).
        refine_fn:          Refiner (Contract R) — proposes mutations from the
                            incumbent's trajectory + failure signatures.
        eval_fn:            arena eval (Contract E) — maps a harness to fitness +
                            trajectory + failure signatures. Use ``mock_codex_eval``
                            until adx's real arena eval lands.
        n_gen:              number of evolution generations (>=1).
        run_seed:           RNG seed for reproducibility.
        apply_fn:           sandbox apply+validate (Contract S); returns H' or None
                            (reject -> rollback). Defaults to ``mock_apply``.
        candidates_per_gen: max children evaluated per generation.
        n_battles:          battles per held-out evaluation (anti-vacuous: >0).
        heldout_manifest:   the frozen, hash-locked held-out tuple set (防偷懒). When
                            given, the run's accumulated training tuples must be DISJOINT
                            from it; overlap -> VOID (inadmissible eval, not REJECT). On a
                            disjoint run the three hashes (probe_lock / heldout / training)
                            are stamped so the promotion is post-hoc provable.
        db_path:            bene.db path for kill-gate persistence; None -> in-memory.
        bus_path:           A2A fleet bus path; None -> default; False -> skip lineage.
    """
    if n_gen < 1:
        raise ValueError("n_gen must be >=1")

    run_id = str(ulid.new())
    store, conn = open_eval_db(db_path)

    # ACT/OBSERVE the seed (baseline).
    seed_eval = eval_fn(seed, run_seed, n_battles)
    seed_fv: CodexFitness = seed_eval.fitness.replace(gens_completed=0)

    # Accumulate every tuple any candidate trained on, for the held-out disjointness gate.
    training_tuples: list[list] = list(seed_eval.training_tuples)

    # Register the hash-locked kill-gate against the seed baseline. The identity
    # self-test (seed vs seed -> uplift 0 -> gate kills) makes the probe admissible.
    probe = build_killgate()
    probe.register(store, conn, baseline=seed_fv, subject_ref=seed.harness_id)

    # Open-ended DGM archive — seeded with H0.
    archive = DGMArchive()
    archive.add(
        harness_id=seed.harness_id,
        content_hash=seed.content_hash(),
        parent_id=None,
        generation=0,
        fitness=seed_fv.to_scores(),
        mutation_kind=None,
        accepted_at_gen=0,
    )

    incumbent, incumbent_eval, incumbent_fv = seed, seed_eval, seed_fv
    best, best_fv = seed, seed_fv
    lineage: list[GenerationLog] = []
    rollbacks = 0
    total_battles = n_battles  # the seed's own evaluation

    for gen in range(1, n_gen + 1):
        # PROPOSE — the Refiner reads the incumbent's trajectory + failures.
        mutations = refine_fn(
            incumbent, incumbent_eval.trajectory, incumbent_eval.failure_signatures
        )

        gen_candidates: list[dict[str, Any]] = []
        # (harness, eval, mutation) of the best child this generation — one optional
        # tuple so a single None-check narrows all three.
        gen_best: tuple[CodexHarness, CodexEvalResult, Mutation] | None = None
        evaluated = 0

        for mutation in mutations:
            if evaluated >= candidates_per_gen:
                break
            # ASSESS — sandbox apply + build/validate.
            child = apply_fn(incumbent, mutation)
            if child is None:
                rollbacks += 1
                gen_candidates.append({
                    "harness_id": None,
                    "parent_id": incumbent.harness_id,
                    "mutation_kind": mutation.kind,
                    "target_path": mutation.target_path,
                    "applied": False,
                    "rejected_reason": "unbuildable",
                    "promoted": False,
                })
                continue

            child_eval = eval_fn(child, run_seed, n_battles)
            total_battles += n_battles
            training_tuples.extend(child_eval.training_tuples)
            evaluated += 1
            gen_candidates.append({
                "harness_id": child.harness_id,
                "parent_id": incumbent.harness_id,
                "mutation_kind": mutation.kind,
                "target_path": mutation.target_path,
                "applied": True,
                "scores": child_eval.fitness.to_scores(),
                "win_rate": child_eval.fitness.win_rate,
                "improved": child_eval.fitness.win_rate > incumbent_fv.win_rate,
                "promoted": False,
            })
            if gen_best is None or child_eval.fitness.win_rate > gen_best[1].fitness.win_rate:
                gen_best = (child, child_eval, mutation)

        # GATE (per generation) — promote the gen-best only if it beats the
        # incumbent; a non-improving best is a rollback (incumbent holds).
        promoted = False
        if gen_best is not None:
            gb_harness, gb_eval, gb_mut = gen_best
            if gb_eval.fitness.win_rate > incumbent_fv.win_rate:
                archive.add(
                    harness_id=gb_harness.harness_id,
                    content_hash=gb_harness.content_hash(),
                    parent_id=incumbent.harness_id,
                    generation=gb_harness.generation,
                    fitness=gb_eval.fitness.to_scores(),
                    mutation_kind=gb_mut.kind,
                    accepted_at_gen=gen,
                )
                for c in gen_candidates:
                    if c.get("harness_id") == gb_harness.harness_id:
                        c["promoted"] = True
                incumbent, incumbent_eval, incumbent_fv = gb_harness, gb_eval, gb_eval.fitness
                if incumbent_fv.win_rate > best_fv.win_rate:
                    best, best_fv = incumbent, incumbent_fv
                promoted = True
            else:
                rollbacks += 1  # a built candidate that did not improve -> rolled back

        lineage.append(GenerationLog(
            gen=gen,
            candidates=gen_candidates,
            incumbent_id=incumbent.harness_id,
            incumbent_scores=incumbent_fv.to_scores(),
            promoted=promoted,
        ))

    best_fv_final = best_fv.replace(gens_completed=n_gen)
    seed_fv_baseline = seed_fv.replace(gens_completed=0)

    accepted_kinds = archive.accepted_mutation_kinds()
    killgate_report: dict[str, Any] = {
        "best_harness_id": best.harness_id,
        "seed_harness_id": seed.harness_id,
        "seed_win_rate": seed_fv.win_rate,
        "best_win_rate": best_fv_final.win_rate,
        "uplift": best_fv_final.win_rate - seed_fv.win_rate,
        "gens_completed": n_gen,
        "battles_played": best_fv_final.battles_played,
        "total_battles_played": total_battles,
        "accepted_mutation_kinds": accepted_kinds,
        "winning_mutation_nonprompt": any(k != "prompt" for k in accepted_kinds),
        "rollbacks": rollbacks,
        "archive_size": len(archive),
    }

    # Held-out anti-overfit gate (防偷懒) — runs BEFORE the win-rate gate. If the run's
    # accumulated training tuples overlap the frozen held-out manifest, the eval is
    # inadmissible -> VOID (distinct from a REJECT of a genuine-but-losing candidate).
    # On a disjoint run the three hashes are stamped so the promotion is post-hoc
    # provable as "scored on data it never trained on".
    voided = False
    if heldout_manifest is not None:
        training_manifest = HeldoutManifest.from_tuples([tuple(t) for t in training_tuples])
        killgate_report["probe_lock_sha256"] = lock_hash(KILLGATE_GATES)
        killgate_report["heldout_manifest_sha256"] = heldout_manifest.manifest_hash()
        killgate_report["training_manifest_sha256"] = training_manifest.manifest_hash()
        ov = overlap(heldout_manifest, training_manifest)
        # A held-out gate can only prove "scored on data it never trained on" when BOTH
        # sets are non-empty: an empty held-out manifest proves nothing, and an empty
        # training manifest (e.g. a Contract-E adapter that reports no training tuples)
        # makes disjointness vacuously true. Either case is inadmissible -> VOID, never a
        # silent pass (PR #65 review).
        if len(heldout_manifest) == 0 or len(training_manifest) == 0:
            voided = True
            reason = (
                "empty_heldout_manifest" if len(heldout_manifest) == 0
                else "empty_training_manifest"
            )
            killgate_report.update({
                "verdict": VOID,
                "probe": PROBE_NAME,
                "killed_gates": [reason],
                "gate_results": [],
                "heldout_overlap_count": 0,
            })
        elif ov:
            voided = True
            killgate_report.update({
                "verdict": VOID,
                "probe": PROBE_NAME,
                "killed_gates": ["heldout_disjointness"],
                "gate_results": [],
                "heldout_overlap_count": len(ov),
            })

    # Final hash-locked kill-gate verdict: best-ever vs seed (anti-vacuous gens stamp).
    if not voided:
        verdict = probe.run(
            subject=best_fv_final,
            baseline=seed_fv_baseline,
            store=store,
            conn=conn,
            subject_ref=best.harness_id,
        )
        killgate_report.update({
            "verdict": verdict.status,
            "probe": verdict.probe_name,
            "killed_gates": verdict.killed_gates,
            "gate_results": verdict.gate_results,
        })

    # SharedLog lineage (best-effort; non-fatal on bus failure).
    if bus_path is not False:
        write_lineage(
            run_id=run_id,
            payload={
                "run_id": run_id,
                "task": "codex-harness-evolution",
                "run_seed": run_seed,
                "n_gen": n_gen,
                "verdict": killgate_report["verdict"],
                "uplift": killgate_report["uplift"],
                "best_harness_id": best.harness_id,
                "archive_size": len(archive),
                "winning_mutation_nonprompt": killgate_report["winning_mutation_nonprompt"],
            },
            **({"bus_path": bus_path} if bus_path is not None else {}),
        )

    return EvolveOutput(
        best=best,
        archive=archive,
        lineage=lineage,
        killgate_report=killgate_report,
    )
