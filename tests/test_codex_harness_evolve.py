"""SECH Contract G (bene-core B1/B2) — evolve_codex_harness tests.

Covers:
  B1  evolve_codex_harness drives >=1 generation via the Refiner, returns EvolveOutput
  B1  the DGM archive is open-ended (keeps every accepted harness + genealogy)
  B2  anti-vacuous (battles_played>0, gens_completed>0) + rollback (unbuildable /
      non-improving H' REJECTED) + a winning NON-PROMPT mutation
  GATE hash-locked kill-gate: ACCEPT on genuine uplift, REJECT on insufficient uplift,
      tamper-refusal

All tests use the mock Refiner/apply/eval (no codex run, no arena server).
"""

from __future__ import annotations

import random

import pytest

from bene.kernel.codex_harness import (
    CodexHarness,
    DGMArchive,
    Mutation,
    build_killgate,
    evolve_codex_harness,
    mock_apply,
    mock_codex_eval,
    mock_refiner,
    open_eval_db,
    seed_codex_harness,
)
from bene.kernel.codex_harness.killgate import KILLGATE_GATES, PROBE_NAME
from bene.kernel.eval.gates import lock_hash
from bene.kernel.eval.verdict import ACCEPT, REJECT


# ---------------------------------------------------------------------------
# B1 — evolution loop shape

def test_evolve_basic_shape():
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=1, run_seed=7, bus_path=False,
    )
    assert isinstance(out.best, CodexHarness)
    assert isinstance(out.archive, DGMArchive)
    assert len(out.lineage) == 1
    assert out.lineage[0].gen == 1
    assert out.killgate_report["gens_completed"] == 1
    assert out.killgate_report["battles_played"] > 0


def test_evolve_rejects_n_gen_zero():
    with pytest.raises(ValueError, match="n_gen must be"):
        evolve_codex_harness(seed_codex_harness(), mock_refiner, mock_codex_eval, n_gen=0)


def test_evolve_multi_gen_accepts_with_uplift():
    """3 generations of mock module-mutations clear the +10pp kill-gate."""
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, bus_path=False,
    )
    assert out.killgate_report["verdict"] == ACCEPT
    assert out.killgate_report["uplift"] >= 0.10
    assert out.killgate_report["killed_gates"] == []


def test_evolve_single_gen_rejects_insufficient_uplift():
    """One generation (~+6pp) does NOT clear the +10pp margin -> REJECT."""
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=1, run_seed=3, bus_path=False,
    )
    assert out.killgate_report["verdict"] == REJECT
    assert "win_rate_uplift" in out.killgate_report["killed_gates"]


# ---------------------------------------------------------------------------
# B1 — DGM archive is open-ended

def test_dgm_archive_keeps_accepted_genealogy():
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, bus_path=False,
    )
    archive = out.archive
    # seed + >=1 accepted per improving gen
    assert len(archive) >= 2
    # the best harness's lineage walks back to the seed
    chain = archive.lineage_of(out.best.harness_id)
    assert chain[-1].parent_id is None  # root = seed
    assert chain[0].harness_id == out.best.harness_id
    # every accepted entry (except seed) records the mutation kind that produced it
    non_seed = [e for e in archive.entries if e.parent_id is not None]
    assert all(e.mutation_kind is not None for e in non_seed)


# ---------------------------------------------------------------------------
# B2 — anti-vacuous + rollback + non-prompt winning mutation

def test_b2_anti_vacuous_counters():
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=2, run_seed=11, bus_path=False,
    )
    r = out.killgate_report
    assert r["battles_played"] > 0
    assert r["gens_completed"] > 0
    assert r["total_battles_played"] > r["battles_played"]


def test_b2_winning_mutation_is_non_prompt():
    """SPEC DONE #2: at least one ACCEPTED mutation is a real code/tool change."""
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, bus_path=False,
    )
    assert out.killgate_report["winning_mutation_nonprompt"] is True
    assert any(k != "prompt" for k in out.killgate_report["accepted_mutation_kinds"])


def test_b2_unbuildable_mutation_is_rolled_back():
    """The mock Refiner emits a deliberately-unbuildable mutation each gen; ASSESS
    must reject it (rollback) and never evaluate it."""
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=2, run_seed=11, bus_path=False,
    )
    assert out.killgate_report["rollbacks"] >= 1
    # the unbuildable candidate appears in the lineage as applied=False
    rejected = [
        c for g in out.lineage for c in g.candidates if not c.get("applied")
    ]
    assert any(c.get("rejected_reason") == "unbuildable" for c in rejected)


def test_apply_rejects_syntax_error_mutation():
    seed = seed_codex_harness()
    bad = Mutation(kind="module", target_path="modules/x.py",
                   diff="def f():\n    return  # SYNTAX_ERROR\n")
    assert mock_apply(seed, bad) is None


def test_apply_exception_counts_as_rollback():
    """A real Contract-S apply_fn rejects a broken mutation by RAISING — the loop must
    treat that as a rollback, not crash (PR #64 review)."""
    def raising_apply(harness, mutation):
        if mutation.provenance.get("unbuildable"):
            raise RuntimeError("cargo build failed")
        return mock_apply(harness, mutation)

    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=2, run_seed=11, apply_fn=raising_apply, bus_path=False,
    )
    assert out.killgate_report["rollbacks"] >= 1
    rejected = [c for g in out.lineage for c in g.candidates if not c.get("applied")]
    assert any(str(c.get("rejected_reason", "")).startswith("apply_error:") for c in rejected)


def test_archive_keeps_every_improving_candidate():
    """Open-ended DGM: when several children beat the incumbent in one generation,
    ALL of them land in the archive, not just the promoted gen-best (PR #64 review)."""
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=1, run_seed=11, bus_path=False,
    )
    gen1 = out.lineage[0]
    archived_in_gen1 = [c for c in gen1.candidates if c.get("archived")]
    assert len(archived_in_gen1) >= 2  # multiple improvers archived, not just the best
    # every archived candidate id is actually in the DGM archive
    archive_ids = {e.harness_id for e in out.archive.entries}
    assert all(c["harness_id"] in archive_ids for c in archived_in_gen1)


def test_total_battles_counts_observed_not_requested():
    """battles_played from the eval (observed) is summed, not the requested n_battles."""
    def observed7_eval(harness, run_seed=0, n_battles=30):
        ev = mock_codex_eval(harness, run_seed, n_battles)
        ev.fitness.battles_played = 7  # arena ran a different count than requested
        return ev

    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, observed7_eval,
        n_gen=2, run_seed=11, n_battles=30, bus_path=False,
    )
    # 7 is coprime with 30, so divisibility by 7 proves observed (not requested) counting
    assert out.killgate_report["total_battles_played"] % 7 == 0
    assert out.killgate_report["total_battles_played"] > 0


def test_prompt_only_refiner_yields_no_nonprompt_winner():
    """A Refiner that only rewrites the prompt cannot satisfy DONE #2."""
    def prompt_only_refiner(harness, trajectory, sigs):
        return [Mutation(kind="prompt", target_path="prompt/system.md",
                         diff=harness.system_prompt + "\nthink step by step",
                         provenance={"strength_delta": 0.2})]

    out = evolve_codex_harness(
        seed_codex_harness(), prompt_only_refiner, mock_codex_eval,
        n_gen=2, run_seed=11, bus_path=False,
    )
    assert out.killgate_report["winning_mutation_nonprompt"] is False


# ---------------------------------------------------------------------------
# GATE — hash-locked kill-gate machinery

def test_killgate_lock_is_stable():
    expected = lock_hash(KILLGATE_GATES)
    assert lock_hash(KILLGATE_GATES) == expected
    assert len(expected) == 64


def test_killgate_tamper_raises(tmp_path):
    from bene.kernel.eval.probe import LockTamperError

    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_killgate()
    seed_fv = mock_codex_eval(seed_codex_harness()).fitness.replace(
        gens_completed=0, battles_played=30
    )
    probe.register(store, conn, baseline=seed_fv)
    conn.execute(
        "UPDATE probe_registry SET gate_spec = ? WHERE name = ?", ("[]", PROBE_NAME)
    )
    conn.commit()
    with pytest.raises(LockTamperError):
        probe.run(
            subject=seed_fv.replace(gens_completed=1),
            baseline=seed_fv, store=store, conn=conn,
        )


# ---------------------------------------------------------------------------
# genome — CodexHarness + Mutation

def test_seed_harness_has_code_resources():
    h0 = seed_codex_harness()
    assert h0.harness_id == "H0-seed"
    assert "modules/lookahead.py" in h0.resources
    assert h0.generation == 0


def test_with_mutation_produces_child():
    h0 = seed_codex_harness()
    m = Mutation(kind="module", target_path="modules/lookahead.py",
                 diff="def best_move(s):\n    return 1\n",
                 provenance={"strength_delta": 0.06})
    child = h0.with_mutation(m)
    assert child.parent_ids == [h0.harness_id]
    assert child.generation == 1
    assert child.resources["modules/lookahead.py"] == m.diff
    assert child.params["_mock_strength"] == pytest.approx(0.06)
    assert child.content_hash() != h0.content_hash()


def test_mutation_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown mutation kind"):
        Mutation(kind="quantum", target_path="x", diff="y")


def test_from_adx_dict_prompt_only_is_valid():
    """A prompt-only BattleHarness dict is a valid CodexHarness (SPEC back-compat)."""
    adx = {"harness_id": "h1", "system_prompt": "play well",
           "move_selection_strategy": "max_damage", "params": {"aggression": 1.0}}
    h = CodexHarness.from_adx_dict(adx)
    assert h.harness_id == "h1"
    assert h.resources == {}


def test_mock_refiner_emits_nonprompt_and_unbuildable():
    h0 = seed_codex_harness()
    muts = mock_refiner(h0, {}, ["loss_vs_baseline", "illegal_move"], random.Random(0))
    assert any(m.kind != "prompt" for m in muts)
    assert any(m.provenance.get("unbuildable") for m in muts)


def test_mock_eval_deterministic_and_never_zero_battles():
    h0 = seed_codex_harness()
    e1 = mock_codex_eval(h0, run_seed=42)
    e2 = mock_codex_eval(h0, run_seed=42)
    assert e1.fitness.win_rate == e2.fitness.win_rate
    assert e1.fitness.battles_played == 30
