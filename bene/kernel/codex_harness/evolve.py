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

import json
import random
import sqlite3
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
from bene.kernel.eval import ACCEPT, REJECT, VOID, Verdict, persist_verdict
from bene.kernel.eval.gates import lock_hash
from bene.kernel.eval.probe import LockTamperError, Probe

RefineFn = Callable[[CodexHarness, dict[str, Any], list[str]], list[Mutation]]
ApplyFn = Callable[[CodexHarness, Mutation], "CodexHarness | None"]
EvalFn = Callable[[CodexHarness, int, int], CodexEvalResult]
# Held-out eval (Contract E restricted to the frozen manifest tuples): maps a harness +
# run_seed + the held-out tuple list to a fitness measured ONLY on those tuples. Optional;
# when given the final kill-gate scores held-out fitness instead of the training window.
HeldoutEvalFn = Callable[[CodexHarness, int, list], CodexEvalResult]


def _register_killgate(
    probe: Probe,
    store: Any,
    conn: sqlite3.Connection,
    *,
    baseline: CodexFitness,
    subject_ref: str | None,
) -> None:
    """Register the hash-locked kill-gate idempotently against a persistent db.

    ``probe_registry.name`` is UNIQUE, so a blind re-INSERT on a 2nd evolve run against the
    SAME db_path raises IntegrityError and aborts the run before any candidate is gated.
    Mirror the proven continual.py ``_ensure_probe`` pattern: reuse an already-registered
    same-name probe (the gate spec is fixed + hash-locked) instead of re-registering; only
    INSERT when absent; if a stored row's lock differs from the in-memory gate spec, raise a
    clear ``LockTamperError`` rather than an opaque IntegrityError. (PR #64 review)
    """
    existing = conn.execute(
        "SELECT probe_id, lock_sha256 FROM probe_registry WHERE name=?", (probe.name,)
    ).fetchone()
    if existing is None:
        try:
            probe.register(store, conn, baseline=baseline, subject_ref=subject_ref)
            return
        except sqlite3.IntegrityError:
            # Lost a race to a concurrent registrant — adopt its row below.
            existing = conn.execute(
                "SELECT probe_id, lock_sha256 FROM probe_registry WHERE name=?",
                (probe.name,),
            ).fetchone()
    if existing is not None:
        if existing[1] != lock_hash(probe.gates):
            raise LockTamperError(
                f"probe {probe.name}: an existing registration's lock differs from the "
                "in-memory gate spec (locked gate spec changed)"
            )
        probe.probe_id = existing[0]  # adopt the registered id so run()/persist link correctly


def _append_harness_engram(store: Any, harness: CodexHarness) -> str:
    """Append a CodexHarness as a first-class engram and return its engram_id.

    The verdict link (verifies/refutes) targets ``engram_links.dst_id`` which FK-references
    ``engrams(engram_id)`` — passing a raw harness_id there creates a dangling link (and
    raises under PRAGMA foreign_keys=ON, as the main engine sets). Persist the harness so the
    verdict->candidate provenance is a real, traversable link. (PR #64 review)

    A genome lives at the ``strategic`` tier 4 — the canonical genome/gene tier used by
    ReflectiveEvolver, GEPA, and the metaharness bridge — so strategic-genome surfaces find
    it. (PR #82 review)
    """
    return store.append(
        "strategic",
        f"codex-harness:{harness.harness_id}",
        harness.to_json(),
        provenance={"system": "bene.kernel.codex_harness.evolve"},
        tier=4,
        metadata={"harness_id": harness.harness_id, "content_hash": harness.content_hash()},
    )


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
    heldout_eval_fn: HeldoutEvalFn | None = None,
    archive_parent_epsilon: float = 0.0,
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
        archive_parent_epsilon: open-ended DGM parent selection. Each generation the parent
                            the Refiner mutates is sampled from the accepted archive (not blindly
                            the incumbent): with prob (1-epsilon) the best accepted entry, else a
                            random accepted ancestor — so an older accepted lineage with a lower
                            immediate win_rate can still be branched from. Default 0.0 = always the
                            best accepted entry (deterministic, archive-driven, back-compatible). The
                            win-rate GATE / ``best`` tracking is unchanged. (PR #67 review)
        heldout_eval_fn:    OPTIONAL held-out runner (Contract E restricted to the manifest
                            tuples). When given AND a disjoint, non-empty held-out manifest is
                            in play, the FINAL kill-gate re-evaluates seed + best on the held-out
                            tuples and gates on THAT fitness — so an ACCEPT stamped with
                            heldout_manifest_sha256 is provably measured on data the harness never
                            trained on, not the training window. None -> the gate re-evaluates on
                            the training window (still a fresh post-selection re-eval). (PR #65 review)
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

    # Persist the seed as a first-class engram so the verdict's verifies/refutes link
    # targets a real engram (FK-clean), not a dangling raw harness_id. (PR #64 review)
    seed_engram_id = _append_harness_engram(store, seed)

    # Register the hash-locked kill-gate against the seed baseline. The identity
    # self-test (seed vs seed -> uplift 0 -> gate kills) makes the probe admissible.
    # Idempotent so a 2nd run on the SAME db_path reuses the locked probe (PR #64 review).
    probe = build_killgate()
    _register_killgate(probe, store, conn, baseline=seed_fv, subject_ref=seed_engram_id)

    # Open-ended DGM archive — seeded with H0. Keep a by_id map of evaluated harnesses +
    # their eval so archive-frontier parent selection can resolve a sampled ancestor back to
    # the real CodexHarness (refine_fn needs its trajectory/failure_signatures). (PR #67 review)
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
    by_id: dict[str, tuple[CodexHarness, CodexEvalResult]] = {seed.harness_id: (seed, seed_eval)}
    parent_rng = random.Random(run_seed)

    incumbent, incumbent_eval, incumbent_fv = seed, seed_eval, seed_fv
    best, best_fv = seed, seed_fv
    lineage: list[GenerationLog] = []
    rollbacks = 0
    # Count OBSERVED battles (what the arena actually ran), not requested — a real
    # Contract-E adapter may return a different battles_played than n_battles (PR #64 review).
    total_battles = seed_eval.fitness.battles_played

    for gen in range(1, n_gen + 1):
        # Open-ended DGM: pick the PARENT the Refiner mutates from the accepted archive,
        # not blindly the current incumbent — so an older accepted ancestor can be branched
        # from (epsilon-greedy; epsilon=0 -> the best accepted entry). Resolve the sampled
        # entry back to the real harness + its eval (refine_fn needs the trajectory/failures);
        # fall back to the incumbent if the entry is not in by_id. The win-rate GATE below
        # still compares the child against the incumbent, so promotion semantics are
        # unchanged — only the mutation parent becomes archive-sampled. (PR #67 review)
        parent_entry = archive.select_parent(parent_rng, epsilon=archive_parent_epsilon)
        if parent_entry is not None and parent_entry.harness_id in by_id:
            parent, parent_eval = by_id[parent_entry.harness_id]
        else:
            parent, parent_eval = incumbent, incumbent_eval

        # PROPOSE — the Refiner reads the parent's trajectory + failures.
        mutations = refine_fn(parent, parent_eval.trajectory, parent_eval.failure_signatures)

        gen_candidates: list[dict[str, Any]] = []
        # (harness, eval, mutation) of the best child this generation — one optional
        # tuple so a single None-check narrows all three.
        gen_best: tuple[CodexHarness, CodexEvalResult, Mutation] | None = None
        evaluated = 0

        for mutation in mutations:
            if evaluated >= candidates_per_gen:
                break
            # ASSESS — sandbox apply + build/validate. A real Contract-S apply_fn may
            # reject a broken mutation by RAISING (not just returning None); either way
            # it is a rollback, never an evolve-loop crash (PR #64 review).
            try:
                child = apply_fn(parent, mutation)
                reject_reason = "unbuildable"
            except Exception as exc:  # noqa: BLE001 — any apply failure is a rollback
                child = None
                reject_reason = f"apply_error:{type(exc).__name__}"
            if child is None:
                rollbacks += 1
                gen_candidates.append(
                    {
                        "harness_id": None,
                        "parent_id": parent.harness_id,
                        "mutation_kind": mutation.kind,
                        "target_path": mutation.target_path,
                        "applied": False,
                        "rejected_reason": reject_reason,
                        "promoted": False,
                    }
                )
                continue

            child_eval = eval_fn(child, run_seed, n_battles)
            total_battles += child_eval.fitness.battles_played  # observed, not requested
            training_tuples.extend(child_eval.training_tuples)
            by_id[child.harness_id] = (child, child_eval)  # resolvable as a future parent
            evaluated += 1
            improved = child_eval.fitness.win_rate > incumbent_fv.win_rate
            gen_candidates.append(
                {
                    "harness_id": child.harness_id,
                    "parent_id": parent.harness_id,
                    "mutation_kind": mutation.kind,
                    "target_path": mutation.target_path,
                    "applied": True,
                    "scores": child_eval.fitness.to_scores(),
                    "win_rate": child_eval.fitness.win_rate,
                    "improved": improved,
                    "archived": improved,
                    "promoted": False,
                }
            )
            # Open-ended DGM: archive EVERY improving candidate, not just the gen-best, so
            # a later generation could branch from any accepted lineage (PR #64 review).
            if improved:
                archive.add(
                    harness_id=child.harness_id,
                    content_hash=child.content_hash(),
                    parent_id=parent.harness_id,
                    generation=child.generation,
                    fitness=child_eval.fitness.to_scores(),
                    mutation_kind=mutation.kind,
                    accepted_at_gen=gen,
                )
            if gen_best is None or child_eval.fitness.win_rate > gen_best[1].fitness.win_rate:
                gen_best = (child, child_eval, mutation)

        # GATE (per generation) — promote the gen-best only if it beats the
        # incumbent; a non-improving best is a rollback (incumbent holds).
        promoted = False
        if gen_best is not None:
            gb_harness, gb_eval, _gb_mut = gen_best
            if gb_eval.fitness.win_rate > incumbent_fv.win_rate:
                # gen_best is already in the DGM archive (every improver is archived in
                # the loop above); here we only advance the incumbent to it.
                for c in gen_candidates:
                    if c.get("harness_id") == gb_harness.harness_id:
                        c["promoted"] = True
                incumbent, incumbent_eval, incumbent_fv = gb_harness, gb_eval, gb_eval.fitness
                if incumbent_fv.win_rate > best_fv.win_rate:
                    best, best_fv = incumbent, incumbent_fv
                promoted = True
            else:
                rollbacks += 1  # a built candidate that did not improve -> rolled back

        lineage.append(
            GenerationLog(
                gen=gen,
                candidates=gen_candidates,
                incumbent_id=incumbent.harness_id,
                incumbent_scores=incumbent_fv.to_scores(),
                promoted=promoted,
            )
        )

    # Report vectors (selection-time fitness) — used ONLY for the lineage/report fields
    # below (best_win_rate / uplift), NOT for the promotion decision.
    best_fv_final = best_fv.replace(gens_completed=n_gen)

    # Persist the winner as a first-class engram so the verdict's verifies/refutes link
    # targets a real engram (not a dangling raw harness_id). Reuse the seed engram when no
    # promotion happened (best is seed). (PR #64 review)
    best_engram_id = seed_engram_id if best is seed else _append_harness_engram(store, best)

    # GATE FITNESS — re-measure the chosen winner + seed FRESH at gate time rather than
    # gating on the cached selection-time vectors (which carry per-eval RNG noise that
    # drove selection). Default: a fresh training-window re-eval of best + seed. When a
    # held-out runner is supplied AND a disjoint non-empty manifest is in play (resolved in
    # the held-out block below), this is replaced by a held-out re-eval so the ACCEPT
    # stamped with heldout_manifest_sha256 is provably measured on data the harness never
    # trained on. (PR #65/#67 review)
    #
    # Deferred until AFTER the held-out admissibility (empty/overlap) checks below so an
    # invalid manifest yields a clean VOID rather than risking a crash/side-effect during a
    # superfluous gate re-eval. Returns the (subject_fv, baseline_fv) pair AND the training
    # tuples the fresh eval(s) tuned on, so those tuples can be folded into the held-out
    # disjointness check + the stamped training_manifest_sha256 (the gate re-eval may use a
    # different CRN window than search). (PR #83 review)
    def _fresh_training_gate() -> tuple[CodexFitness, CodexFitness, list[list]]:
        if best is seed:
            # No promotion: the identity gate (seed vs seed -> 0 uplift) is exactly the
            # admissibility self-test; re-eval once and reuse for both sides.
            ev = eval_fn(seed, run_seed, n_battles)
            return (
                ev.fitness.replace(gens_completed=n_gen),
                ev.fitness.replace(gens_completed=0),
                list(ev.training_tuples),
            )
        best_ev = eval_fn(best, run_seed, n_battles)
        seed_ev = eval_fn(seed, run_seed, n_battles)
        return (
            best_ev.fitness.replace(gens_completed=n_gen),
            seed_ev.fitness.replace(gens_completed=0),
            [*best_ev.training_tuples, *seed_ev.training_tuples],
        )

    gate_subject_fv: CodexFitness
    gate_baseline_fv: CodexFitness
    if heldout_manifest is None:
        # No held-out manifest: gate on a fresh training-window re-eval (no manifest stamps).
        gate_subject_fv, gate_baseline_fv, _ = _fresh_training_gate()

    accepted_kinds = archive.accepted_mutation_kinds()
    # winning_mutation_nonprompt (SPEC DONE #2) must reflect the BEST/promoted LINEAGE only,
    # NOT every archived improver. Open-ended DGM archives every child that beats the
    # incumbent, so a non-prompt side branch that was archived but never promoted would
    # otherwise flip this flag True even when the winning lineage is prompt-only — letting a
    # caller enforcing SPEC DONE #2 accept the wrong (prompt-only) run. Walk best's genealogy
    # back to the seed and derive the flag from those mutation kinds. (PR #67 review)
    winning_kinds = [
        e.mutation_kind for e in archive.lineage_of(best.harness_id) if e.mutation_kind is not None
    ]
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
        "winning_mutation_kinds": winning_kinds,
        "winning_mutation_nonprompt": any(k != "prompt" for k in winning_kinds),
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

        def _void(killed: str, overlap_count: int) -> None:
            nonlocal voided
            voided = True
            killgate_report.update(
                {
                    "verdict": VOID,
                    "probe": PROBE_NAME,
                    "killed_gates": [killed],
                    "gate_results": [],
                    "heldout_overlap_count": overlap_count,
                }
            )

        def _stamp_training(tuples: list[list]) -> HeldoutManifest:
            tm = HeldoutManifest.from_tuples([tuple(t) for t in tuples])
            killgate_report["training_manifest_sha256"] = tm.manifest_hash()
            return tm

        training_manifest = HeldoutManifest.from_tuples([tuple(t) for t in training_tuples])
        killgate_report["probe_lock_sha256"] = lock_hash(KILLGATE_GATES)
        killgate_report["heldout_manifest_sha256"] = heldout_manifest.manifest_hash()
        killgate_report["training_manifest_sha256"] = training_manifest.manifest_hash()
        ov = overlap(heldout_manifest, training_manifest)
        # ADMISSIBILITY (PR #65 + PR #83 review) — run BEFORE any fresh gate-time eval_fn
        # call so an invalid manifest yields a clean VOID rather than risking a crash/side
        # effect during a superfluous gate re-eval. A held-out gate can only prove "scored
        # on data it never trained on" when BOTH sets are non-empty: an empty held-out
        # manifest proves nothing, and an empty training manifest (e.g. a Contract-E adapter
        # that reports no training tuples) makes disjointness vacuously true. Either case is
        # inadmissible -> VOID, never a silent pass.
        if len(heldout_manifest) == 0 or len(training_manifest) == 0:
            _void(
                "empty_heldout_manifest"
                if len(heldout_manifest) == 0
                else "empty_training_manifest",
                0,
            )
        elif ov:
            _void("heldout_disjointness", len(ov))
        elif heldout_eval_fn is not None:
            # ADMISSIBLE (disjoint, non-empty) + a held-out runner is supplied: re-measure
            # best + seed on the held-out tuples and gate on THAT fitness, so the ACCEPT
            # stamped with heldout_manifest_sha256 is provably measured on held-out data, not
            # the training window. Defend against an adapter silently scoring the training
            # window: each side's reported tuples must EQUAL the manifest, else VOID. (PR #65
            # + PR #83 review)
            heldout_tuples_list = [list(t) for t in heldout_manifest.tuples]
            best_ho = heldout_eval_fn(best, run_seed, heldout_tuples_list)
            seed_ho = heldout_eval_fn(seed, run_seed, heldout_tuples_list)
            manifest_hashes = heldout_manifest.tuple_hashes()
            best_scored = HeldoutManifest.from_tuples(
                [tuple(t) for t in best_ho.training_tuples]
            ).tuple_hashes()
            seed_scored = HeldoutManifest.from_tuples(
                [tuple(t) for t in seed_ho.training_tuples]
            ).tuple_hashes()
            # A held-out ACCEPT may only be stamped if the runner PROVABLY scored on the WHOLE
            # held-out manifest: EACH side (best AND seed) must report >0 scored tuples (else
            # we cannot prove it didn't silently score the training window) AND each side's
            # scored set must EQUAL the manifest — a proper subset would let a winner scored on
            # one easy held-out tuple still ACCEPT with the full heldout_manifest_sha256 stamp,
            # and an escaped tuple would mean it left the manifest. Any failure -> VOID, not a
            # vacuous ACCEPT. (PR #65 + PR #80 + PR #83 review)
            if not best_scored or not seed_scored:
                _void("heldout_eval_scored_no_tuples", 0)
            elif best_scored != manifest_hashes or seed_scored != manifest_hashes:
                # Escaped off-manifest OR covered only a proper subset of the manifest.
                _void("heldout_eval_escaped_manifest", 0)
            # Anti-vacuous baseline: a held-out comparison with zero OBSERVED battles on
            # EITHER side (an arena timeout / empty baseline window) cannot ground the final
            # verdict — the subject-only battles_played_gt0 gate would not catch a baseline
            # with 0 observations. VOID before using these vectors. (PR #83 review)
            elif best_ho.fitness.battles_played == 0 or seed_ho.fitness.battles_played == 0:
                _void("heldout_eval_no_battles", 0)
            else:
                gate_subject_fv = best_ho.fitness.replace(gens_completed=n_gen)
                gate_baseline_fv = seed_ho.fitness.replace(gens_completed=0)
                killgate_report["scored_on_heldout"] = True
        else:
            # ADMISSIBLE (disjoint, non-empty) but NO held-out runner: gate on a fresh
            # training-window re-eval. The gate re-eval may tune on a different CRN window
            # than search (incl. a held-out tuple), so union ITS training tuples into the
            # disjointness check + the stamped training_manifest_sha256 — else an audit hash
            # omits data the gate-time winner was evaluated on, and a held-out tuple could
            # leak through unchecked. (PR #83 review)
            gate_subject_fv, gate_baseline_fv, gate_tuples = _fresh_training_gate()
            training_manifest = _stamp_training([*training_tuples, *gate_tuples])
            ov2 = overlap(heldout_manifest, training_manifest)
            if len(training_manifest) == 0:
                _void("empty_training_manifest", 0)
            elif ov2:
                _void("heldout_disjointness", len(ov2))

    # The voided branch above bypasses probe.run(), which is what normally persists the
    # verdict to eval engrams + experiment_runs. Persist the VOID ourselves so it is a
    # first-class record — otherwise `bene experiments ls` misses a run that killgate_report
    # reports as VOID, and no refutes-link/engram exists for it. (PR #66 review)
    if voided:
        persist_verdict(
            Verdict(
                status=VOID,
                probe_name=PROBE_NAME,
                gate_results=[{"name": g, "killed": True} for g in killgate_report["killed_gates"]],
                reason=killgate_report["killed_gates"][0],
            ),
            store=store,
            conn=conn,
            probe_id=probe.probe_id,
            subject_ref=best_engram_id,
        )

    # Final hash-locked kill-gate verdict: best-ever vs seed scored on the FRESH gate
    # vectors (a post-selection re-eval — held-out when a runner was supplied — not the
    # cached selection-time fitness; anti-vacuous gens stamp).
    if not voided:
        # Compute the gate verdict WITHOUT persisting, fold in SPEC DONE #2 (below), then
        # persist exactly ONE verdict — otherwise a prompt-only winner that clears
        # win_rate_uplift would leave a stale ACCEPT verdict + verifies-link in the ledger
        # contradicting the REJECT report (a naive `status='ACCEPT'` traversal would surface
        # it). (PR #80 review)
        verdict = probe.run(
            subject=gate_subject_fv,
            baseline=gate_baseline_fv,
            store=store,
            conn=conn,
            subject_ref=best_engram_id,
            persist=False,
        )
        final_status = verdict.status
        final_results = list(verdict.gate_results)
        final_reason = verdict.reason
        # SPEC DONE #2 — a prompt-only winning lineage must NOT promote even when it clears
        # win_rate_uplift: the contract requires at least one ACCEPTED non-prompt (code/tool/
        # arch) change. The hash-locked gates don't see mutation kind, so fold the requirement
        # into the FINAL verdict here — a caller promoting on killgate_report["verdict"]
        # cannot accept a prompt-only run. (PR #67 review)
        if final_status == ACCEPT and not killgate_report["winning_mutation_nonprompt"]:
            final_status = REJECT
            final_results = [
                *verdict.gate_results,
                {"name": "winning_mutation_nonprompt", "killed": True},
            ]
            final_reason = (
                "winning lineage is prompt-only (SPEC DONE #2 requires a non-prompt mutation)"
            )
        persisted = persist_verdict(
            Verdict(
                status=final_status,
                probe_name=PROBE_NAME,
                gate_results=final_results,
                reason=final_reason,
            ),
            store=store,
            conn=conn,
            probe_id=probe.probe_id,
            subject_ref=best_engram_id,
        )
        killgate_report.update(
            {
                "verdict": persisted.status,
                "probe": persisted.probe_name,
                "killed_gates": persisted.killed_gates,
                "gate_results": persisted.gate_results,
            }
        )

    # Persist the held-out promotion stamp (the 3 provenance hashes + verdict) as a durable
    # eval engram so the audit trail survives the process — mirroring eval/heldout.py's
    # HeldoutGate.score. Emitted on BOTH the disjoint/ACCEPT path and the VOID path (whenever
    # a manifest was in play), so the run is post-exit provable regardless of outcome. (PR #66 review)
    if heldout_manifest is not None:
        stamp = {
            "best_harness_id": best.harness_id,
            "verdict": killgate_report["verdict"],
            "probe_lock_sha256": killgate_report["probe_lock_sha256"],
            "heldout_manifest_sha256": killgate_report["heldout_manifest_sha256"],
            "training_manifest_sha256": killgate_report["training_manifest_sha256"],
        }
        store.append(
            "eval",
            f"heldout-promotion-stamp:{PROBE_NAME}",
            json.dumps(stamp),
            provenance={"system": "bene.kernel.codex_harness.evolve"},
            metadata=stamp,
        )

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
