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
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=1,
        run_seed=7,
        bus_path=False,
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
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        bus_path=False,
    )
    assert out.killgate_report["verdict"] == ACCEPT
    assert out.killgate_report["uplift"] >= 0.10
    assert out.killgate_report["killed_gates"] == []


def test_evolve_single_gen_rejects_insufficient_uplift():
    """One generation (~+6pp) does NOT clear the +10pp margin -> REJECT."""
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=1,
        run_seed=3,
        bus_path=False,
    )
    assert out.killgate_report["verdict"] == REJECT
    assert "win_rate_uplift" in out.killgate_report["killed_gates"]


# ---------------------------------------------------------------------------
# B1 — DGM archive is open-ended


def test_dgm_archive_keeps_accepted_genealogy():
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        bus_path=False,
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
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=2,
        run_seed=11,
        bus_path=False,
    )
    r = out.killgate_report
    assert r["battles_played"] > 0
    assert r["gens_completed"] > 0
    assert r["total_battles_played"] > r["battles_played"]


def test_b2_winning_mutation_is_non_prompt():
    """SPEC DONE #2: at least one ACCEPTED mutation is a real code/tool change."""
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        bus_path=False,
    )
    assert out.killgate_report["winning_mutation_nonprompt"] is True
    assert any(k != "prompt" for k in out.killgate_report["accepted_mutation_kinds"])


def test_b2_unbuildable_mutation_is_rolled_back():
    """The mock Refiner emits a deliberately-unbuildable mutation each gen; ASSESS
    must reject it (rollback) and never evaluate it."""
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=2,
        run_seed=11,
        bus_path=False,
    )
    assert out.killgate_report["rollbacks"] >= 1
    # the unbuildable candidate appears in the lineage as applied=False
    rejected = [c for g in out.lineage for c in g.candidates if not c.get("applied")]
    assert any(c.get("rejected_reason") == "unbuildable" for c in rejected)


def test_apply_rejects_syntax_error_mutation():
    seed = seed_codex_harness()
    bad = Mutation(
        kind="module", target_path="modules/x.py", diff="def f():\n    return  # SYNTAX_ERROR\n"
    )
    assert mock_apply(seed, bad) is None


def test_apply_exception_counts_as_rollback():
    """A real Contract-S apply_fn rejects a broken mutation by RAISING — the loop must
    treat that as a rollback, not crash (PR #64 review)."""

    def raising_apply(harness, mutation):
        if mutation.provenance.get("unbuildable"):
            raise RuntimeError("cargo build failed")
        return mock_apply(harness, mutation)

    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=2,
        run_seed=11,
        apply_fn=raising_apply,
        bus_path=False,
    )
    assert out.killgate_report["rollbacks"] >= 1
    rejected = [c for g in out.lineage for c in g.candidates if not c.get("applied")]
    assert any(str(c.get("rejected_reason", "")).startswith("apply_error:") for c in rejected)


def test_archive_keeps_every_improving_candidate():
    """Open-ended DGM: when several children beat the incumbent in one generation,
    ALL of them land in the archive, not just the promoted gen-best (PR #64 review)."""
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=1,
        run_seed=11,
        bus_path=False,
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
        seed_codex_harness(),
        mock_refiner,
        observed7_eval,
        n_gen=2,
        run_seed=11,
        n_battles=30,
        bus_path=False,
    )
    # 7 is coprime with 30, so divisibility by 7 proves observed (not requested) counting
    assert out.killgate_report["total_battles_played"] % 7 == 0
    assert out.killgate_report["total_battles_played"] > 0


def test_prompt_only_refiner_yields_no_nonprompt_winner():
    """A Refiner that only rewrites the prompt cannot satisfy DONE #2."""

    def prompt_only_refiner(harness, trajectory, sigs):
        return [
            Mutation(
                kind="prompt",
                target_path="prompt/system.md",
                diff=harness.system_prompt + "\nthink step by step",
                provenance={"strength_delta": 0.2},
            )
        ]

    out = evolve_codex_harness(
        seed_codex_harness(),
        prompt_only_refiner,
        mock_codex_eval,
        n_gen=2,
        run_seed=11,
        bus_path=False,
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
    conn.execute("UPDATE probe_registry SET gate_spec = ? WHERE name = ?", ("[]", PROBE_NAME))
    conn.commit()
    with pytest.raises(LockTamperError):
        probe.run(
            subject=seed_fv.replace(gens_completed=1),
            baseline=seed_fv,
            store=store,
            conn=conn,
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
    m = Mutation(
        kind="module",
        target_path="modules/lookahead.py",
        diff="def best_move(s):\n    return 1\n",
        provenance={"strength_delta": 0.06},
    )
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
    adx = {
        "harness_id": "h1",
        "system_prompt": "play well",
        "move_selection_strategy": "max_damage",
        "params": {"aggression": 1.0},
    }
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


def test_lineage_writer_ref_id_is_null_not_run_id(tmp_path):
    """PR #66 review: the ULID run_id must NOT be written into shared_log.ref_id
    (an INTEGER FK to log_id) — it lives in the payload and ref_id stays NULL, so
    the row is FK-clean for ref/thread readers and FK-enabled writers."""
    import json
    import sqlite3

    from bene.kernel.codex_harness.lineage import write_lineage

    bus = str(tmp_path / "bus.db")
    con = sqlite3.connect(bus)
    con.execute(
        "CREATE TABLE IF NOT EXISTS shared_log "
        "(log_id INTEGER PRIMARY KEY AUTOINCREMENT, position INTEGER NOT NULL, "
        " type TEXT NOT NULL CHECK (type IN "
        "  ('intent','vote','decision','commit','result','abort','policy','mail')), "
        " agent_id TEXT, ref_id INTEGER REFERENCES shared_log(log_id), payload TEXT, "
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    con.commit()
    con.close()

    log_id = write_lineage("01J-run-ulid", {"verdict": "VOID"}, bus_path=bus)
    assert log_id is not None

    con = sqlite3.connect(bus)
    con.execute("PRAGMA foreign_keys=ON")
    row = con.execute("SELECT ref_id, payload FROM shared_log").fetchone()
    assert row[0] is None  # ref_id is the INTEGER thread FK, never the ULID run_id
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert json.loads(row[1])["run_id"] == "01J-run-ulid"  # run id preserved in payload
    con.close()


def test_winning_flag_ignores_nonprompt_side_branch():
    """Open-ended DGM archives EVERY improving child, but winning_mutation_nonprompt
    (SPEC DONE #2) must reflect only the BEST/promoted lineage. A non-prompt child that
    beats the incumbent but is NOT promoted must not flip the flag when the winner is
    prompt-only — else a caller enforcing SPEC DONE #2 accepts the wrong run (PR #67 review)."""
    from bene.kernel.codex_harness import CodexEvalResult

    PROMPT_WINNER = "SYSTEM PROMPT V2 — the winner"

    def refine(harness, trajectory, signatures):
        # one prompt child (scores highest -> promoted) + one module child (improves over
        # the incumbent, so it is archived, but is NOT the gen-best).
        return [
            Mutation(kind="prompt", target_path="prompts/system.md", diff=PROMPT_WINNER),
            Mutation(kind="module", target_path="modules/y.py", diff="def y():\n    return 1\n"),
        ]

    def evaluate(harness, run_seed=0, n_battles=30):
        base = mock_codex_eval(harness, run_seed, n_battles)
        if PROMPT_WINNER in harness.system_prompt:
            wr = 0.80  # prompt child — highest -> gen-best -> promoted (the winning lineage)
        elif "modules/y.py" in harness.resources:
            wr = 0.65  # module child — beats seed (archived) but NOT promoted (side branch)
        else:
            wr = 0.50  # seed / incumbent
        return CodexEvalResult(
            fitness=base.fitness.replace(win_rate=wr, battles_played=30, gens_completed=0),
            trajectory=base.trajectory,
            failure_signatures=base.failure_signatures,
            training_tuples=base.training_tuples,
        )

    out = evolve_codex_harness(
        seed_codex_harness(), refine, evaluate, n_gen=1, run_seed=1, bus_path=False
    )
    r = out.killgate_report
    # the non-prompt side branch WAS archived (open-ended DGM keeps every improver)…
    assert "module" in r["accepted_mutation_kinds"]
    # …but the winning lineage is prompt-only, so the SPEC-DONE-#2 flag must be False.
    # (The pre-fix code derived this from the whole archive and wrongly reported True.)
    assert r["winning_mutation_nonprompt"] is False
    assert r["winning_mutation_kinds"] == ["prompt"]


# ---------------------------------------------------------------------------
# Review follow-ups (PR #64-#67) — regression tests


def test_second_evolve_run_on_same_db_does_not_crash(tmp_path):
    """Re-registering the fixed kill-gate probe name on a PERSISTENT db must be
    idempotent: a 2nd evolve_codex_harness run against the same db_path reuses the locked
    probe rather than raising sqlite3.IntegrityError (UNIQUE probe_registry.name). (CID 3440239260)"""
    db = str(tmp_path / "evo.db")
    out1 = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        db_path=db,
        bus_path=False,
    )
    # The crash (pre-fix) happens on the SECOND run's blind re-INSERT.
    out2 = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        db_path=db,
        bus_path=False,
    )
    assert out1.killgate_report["verdict"] == out2.killgate_report["verdict"]


def test_child_id_is_deterministic_content_addressed():
    """with_mutation must derive the child id deterministically from the parent+mutation
    (content hash), NOT a fresh time/random ULID — else the mock eval (which seeds its RNG
    off harness_id) and the kill-gate become nondeterministic across replays. (CID 3440239274)"""
    h0 = seed_codex_harness()
    m = Mutation(
        kind="module",
        target_path="modules/lookahead.py",
        diff="def best_move(s):\n    return 1\n",
        provenance={"strength_delta": 0.06},
    )
    c1 = h0.with_mutation(m)
    c2 = h0.with_mutation(m)
    assert c1.harness_id == c2.harness_id  # reproducible
    assert c1.harness_id.startswith(f"{h0.harness_id}-g1-")
    assert c1.harness_id != h0.harness_id
    # the deterministic id makes a full run reproducible end-to-end
    a = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval, n_gen=3, run_seed=11, bus_path=False
    )
    b = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval, n_gen=3, run_seed=11, bus_path=False
    )
    assert a.best.harness_id == b.best.harness_id


def test_content_hash_distinguishes_harness_ref():
    """content_hash() must fold in harness_ref so two genomes with identical heads but
    different on-disk resource dirs never collide in the DGM archive. (CID 3440239268)"""
    a = CodexHarness(
        harness_id="a",
        system_prompt="p",
        move_selection_strategy="max_damage",
        harness_ref="/harnesses/A",
        resources={"m.py": "x"},
    )
    b = CodexHarness(
        harness_id="b",
        system_prompt="p",
        move_selection_strategy="max_damage",
        harness_ref="/harnesses/B",
        resources={"m.py": "x"},
    )
    assert a.content_hash() != b.content_hash()


def test_from_adx_dict_rejects_ref_without_resources():
    """A harness_ref with no loaded resources would content-address by head alone (collision
    risk) — from_adx_dict must reject it. (CID 3440239268)"""
    with pytest.raises(ValueError, match="resources is empty"):
        CodexHarness.from_adx_dict(
            {
                "harness_id": "h",
                "system_prompt": "p",
                "harness_ref": "/harnesses/X",  # set but resources omitted
            }
        )


def test_archive_select_parent_can_branch_off_non_incumbent():
    """The DGM archive must be READ for parent selection (not passive bookkeeping): with
    epsilon=1.0 select_parent samples a non-best accepted ancestor. (CID 3440239283)"""
    import random as _random

    arch = DGMArchive()
    arch.add(
        harness_id="seed",
        content_hash="h0",
        parent_id=None,
        generation=0,
        fitness={"win_rate": 0.5},
        mutation_kind=None,
        accepted_at_gen=0,
    )
    arch.add(
        harness_id="lo",
        content_hash="h1",
        parent_id="seed",
        generation=1,
        fitness={"win_rate": 0.55},
        mutation_kind="module",
        accepted_at_gen=1,
    )
    arch.add(
        harness_id="hi",
        content_hash="h2",
        parent_id="seed",
        generation=1,
        fitness={"win_rate": 0.90},
        mutation_kind="module",
        accepted_at_gen=1,
    )
    # epsilon=0 -> always the best accepted entry (archive-driven, not blind incumbent)
    assert arch.select_parent(_random.Random(0), epsilon=0.0).harness_id == "hi"
    # epsilon=1 -> explore: over many draws a non-best ("seed"/"lo") IS selected
    picks = {arch.select_parent(_random.Random(s), epsilon=1.0).harness_id for s in range(50)}
    assert picks - {"hi"}  # at least one non-best ancestor branched from


def test_prompt_only_winner_is_rejected_not_accepted():
    """A prompt-only winning lineage that clears win_rate_uplift must NOT yield ACCEPT:
    SPEC DONE #2 (a non-prompt mutation) is folded into the FINAL verdict, so a caller
    promoting on killgate_report['verdict'] cannot accept a prompt-only run. (CID 3440239293)"""
    from bene.kernel.codex_harness import CodexEvalResult

    PROMPT_WINNER = "SYSTEM PROMPT V2 — the winner"

    def prompt_only_refine(harness, trajectory, signatures):
        return [Mutation(kind="prompt", target_path="prompts/system.md", diff=PROMPT_WINNER)]

    def evaluate(harness, run_seed=0, n_battles=30):
        base = mock_codex_eval(harness, run_seed, n_battles)
        wr = 0.80 if PROMPT_WINNER in harness.system_prompt else 0.50  # +30pp clears uplift
        return CodexEvalResult(
            fitness=base.fitness.replace(win_rate=wr, battles_played=30, gens_completed=0),
            trajectory=base.trajectory,
            failure_signatures=base.failure_signatures,
            training_tuples=base.training_tuples,
        )

    out = evolve_codex_harness(
        seed_codex_harness(), prompt_only_refine, evaluate, n_gen=1, run_seed=1, bus_path=False
    )
    r = out.killgate_report
    assert r["uplift"] >= 0.10  # the prompt-only winner DID clear the win-rate margin…
    assert r["winning_mutation_nonprompt"] is False
    assert r["verdict"] == REJECT  # …but the verdict is REJECT, not ACCEPT
    assert "winning_mutation_nonprompt" in r["killed_gates"]


def test_gate_scores_a_fresh_post_selection_re_eval(tmp_path):
    """The kill-gate must score a FRESH re-eval of the winner at gate time, not the cached
    selection-time vector. A noisy eval whose 2nd call (the gate re-eval) drops the winner
    below the +10pp margin must flip ACCEPT->REJECT. (CID 3440239279)"""
    from bene.kernel.codex_harness import CodexEvalResult

    PROMPT = seed_codex_harness().system_prompt
    state = {"best_calls": 0}

    def refine(harness, trajectory, signatures):
        return [
            Mutation(
                kind="module",
                target_path="modules/m.py",
                diff="def m():\n    return 1\n",
                provenance={"strength_delta": 0.3},
            )
        ]

    def evaluate(harness, run_seed=0, n_battles=30):
        base = mock_codex_eval(harness, run_seed, n_battles)
        is_seed = harness.system_prompt == PROMPT and "modules/m.py" not in harness.resources
        if is_seed:
            wr = 0.50
        else:
            # the winner: high at SELECTION time, but the gate re-eval (a later call) reads low
            state["best_calls"] += 1
            wr = 0.90 if state["best_calls"] == 1 else 0.52  # 2nd read (gate) -> only +2pp
        return CodexEvalResult(
            fitness=base.fitness.replace(win_rate=wr, battles_played=30, gens_completed=0),
            trajectory=base.trajectory,
            failure_signatures=base.failure_signatures,
            training_tuples=base.training_tuples,
        )

    out = evolve_codex_harness(
        seed_codex_harness(),
        refine,
        evaluate,
        n_gen=1,
        run_seed=1,
        db_path=str(tmp_path / "g.db"),
        bus_path=False,
    )
    # selection saw +40pp (best_win_rate 0.90) but the FRESH gate re-eval saw +2pp -> REJECT
    assert out.killgate_report["best_win_rate"] == 0.90
    assert out.killgate_report["verdict"] == REJECT
    assert "win_rate_uplift" in out.killgate_report["killed_gates"]


def test_verdict_link_targets_a_real_engram_under_fk(tmp_path):
    """The verdict's verifies/refutes link must target a REAL engram (FK-clean), not a
    dangling raw harness_id — assert no foreign-key violations after a run. (CID 3440239282)"""
    import sqlite3

    db = str(tmp_path / "fk.db")
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        db_path=db,
        bus_path=False,
    )
    assert out.killgate_report["verdict"] == ACCEPT
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    # every engram_links.dst_id must resolve to an engrams row (no dangling harness_id link)
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    dangling = con.execute(
        "SELECT COUNT(*) FROM engram_links l "
        "WHERE NOT EXISTS (SELECT 1 FROM engrams e WHERE e.engram_id = l.dst_id)"
    ).fetchone()[0]
    con.close()
    assert dangling == 0


def test_prompt_only_winner_persists_no_stale_accept_verdict(tmp_path):
    """A prompt-only winner that clears win_rate_uplift is downgraded to REJECT (SPEC DONE #2).
    The durable eval ledger must then hold NO stale ACCEPT verdict / verifies-link from the
    probe.run() that scored the gates before the downgrade — exactly one REJECT is persisted.
    (CID 3440239293 follow-up: persist the FINAL verdict once via probe.run(persist=False).)"""
    import sqlite3

    from bene.kernel.codex_harness import CodexEvalResult

    PROMPT_WINNER = "SYSTEM PROMPT V2 — the winner"

    def prompt_only_refine(harness, trajectory, signatures):
        return [Mutation(kind="prompt", target_path="prompts/system.md", diff=PROMPT_WINNER)]

    def evaluate(harness, run_seed=0, n_battles=30):
        base = mock_codex_eval(harness, run_seed, n_battles)
        wr = 0.80 if PROMPT_WINNER in harness.system_prompt else 0.50  # +30pp clears uplift
        return CodexEvalResult(
            fitness=base.fitness.replace(win_rate=wr, battles_played=30, gens_completed=0),
            trajectory=base.trajectory,
            failure_signatures=base.failure_signatures,
            training_tuples=base.training_tuples,
        )

    db = str(tmp_path / "po.db")
    out = evolve_codex_harness(
        seed_codex_harness(),
        prompt_only_refine,
        evaluate,
        n_gen=1,
        run_seed=1,
        db_path=db,
        bus_path=False,
    )
    assert out.killgate_report["verdict"] == REJECT
    con = sqlite3.connect(db)
    # no ACCEPT verdict engram, and no verifies-link survives for the REJECTED prompt-only run
    accept_verdicts = con.execute(
        "SELECT COUNT(*) FROM engrams WHERE kind='eval' AND title LIKE 'verdict:%' "
        "AND json_extract(metadata,'$.status')=?",
        (ACCEPT,),
    ).fetchone()[0]
    verifies = con.execute(
        "SELECT COUNT(*) FROM engram_links WHERE link_type='verifies'"
    ).fetchone()[0]
    con.close()
    assert accept_verdicts == 0, "stale ACCEPT verdict left in the ledger"
    assert verifies == 0, "stale verifies-link left for a prompt-only (REJECTED) winner"
