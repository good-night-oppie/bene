"""Lane B — BattleHarness evolution bridge tests.

Covers:
  B1  evolve_battle_harness drives ≥1 generation, returns EvolveOutput
  B2  Pareto evaluator wired to all 5 Contract-3 dimensions
  B3  kill-gate: hash-locked, anti-vacuous (battles_played>0, gens_completed>0),
      rejects identity candidate, accepts genuinely improved candidate
  B4  SharedLog lineage writer (bus fallback)

All tests use mock_fitness (no real battle server needed).
"""

from __future__ import annotations

import json
import random
import sqlite3

import pytest

from bene.kernel.battle.evolve import evolve_battle_harness
from bene.kernel.battle.genome import (
    BattleHarness,
    CONTRACT3_OBJECTIVES,
    mock_fitness,
    seed_harness,
)
from bene.kernel.battle.killgate import (
    KILLGATE_GATES,
    PROBE_NAME,
    build_killgate,
    open_eval_db,
)
from bene.kernel.battle.lineage import write_lineage
from bene.kernel.eval.gates import lock_hash
from bene.kernel.eval.verdict import ACCEPT, REJECT
from bene.metaharness.pareto import compute_pareto


# ---------------------------------------------------------------------------
# B1 — evolution loop produces output with correct shape

def test_evolve_basic_shape():
    h0 = seed_harness()
    out = evolve_battle_harness(h0, mock_fitness, n_gen=1, run_seed=7, bus_path=False)

    assert out.best is not None
    assert isinstance(out.best, BattleHarness)
    assert len(out.lineage) == 1
    assert out.lineage[0].gen == 1
    assert len(out.lineage[0].candidates) == 3  # default candidates_per_gen
    assert out.killgate_report["gens_completed"] == 1
    assert out.killgate_report["battles_played"] > 0


def test_evolve_multi_gen():
    h0 = seed_harness()
    out = evolve_battle_harness(h0, mock_fitness, n_gen=3, run_seed=99, bus_path=False)
    assert len(out.lineage) == 3
    assert out.killgate_report["gens_completed"] == 3


def test_evolve_rejects_n_gen_zero():
    with pytest.raises(ValueError, match="n_gen must be"):
        evolve_battle_harness(seed_harness(), mock_fitness, n_gen=0)


# ---------------------------------------------------------------------------
# B2 — Pareto evaluator covers all 5 Contract-3 dimensions

def test_pareto_has_all_contract3_dims():
    results_data = [
        ("h1", {"win_rate": 0.6, "elo": 1100.0, "move_legibility": 0.7,
                "no_forfeit_exploit": 0.9, "turn_efficiency": 0.8,
                "battles_played": 30.0, "gens_completed": 1.0}),
        ("h2", {"win_rate": 0.5, "elo": 900.0, "move_legibility": 0.8,
                "no_forfeit_exploit": 0.95, "turn_efficiency": 0.9,
                "battles_played": 30.0, "gens_completed": 1.0}),
    ]
    from bene.metaharness.harness import EvaluationResult
    results = [EvaluationResult(harness_id=hid, scores=s) for hid, s in results_data]

    pareto = compute_pareto(results, CONTRACT3_OBJECTIVES)
    assert len(pareto.points) >= 1
    for p in pareto.points:
        for dim in CONTRACT3_OBJECTIVES:
            assert dim in p.scores, f"Pareto point missing dim {dim!r}"


def test_evolve_pareto_non_empty():
    out = evolve_battle_harness(seed_harness(), mock_fitness, n_gen=2, run_seed=5,
                                bus_path=False)
    assert len(out.pareto.points) >= 1
    for p in out.pareto.points:
        for dim in CONTRACT3_OBJECTIVES:
            assert dim in p.scores


# ---------------------------------------------------------------------------
# B3 — kill-gate: hash-locked + admissible + correct ACCEPT/REJECT outcomes

def test_killgate_lock_is_stable():
    """The lock hash must be deterministic — editing gates breaks the lock."""
    expected = lock_hash(KILLGATE_GATES)
    # compute twice to verify determinism
    assert lock_hash(KILLGATE_GATES) == expected
    assert len(expected) == 64  # sha256 hex


def test_killgate_admissible_on_seed():
    """Identity run (seed vs seed) must trigger at least one kill gate."""
    from bene.kernel.eval.gates import evaluate_gate

    seed_fv = mock_fitness(seed_harness(), run_seed=0).replace(gens_completed=0)
    seed_metrics = {
        "win_rate": seed_fv.win_rate,
        "battles_played": float(seed_fv.battles_played),
        "gens_completed": float(seed_fv.gens_completed),
    }
    killed = [
        evaluate_gate(g, seed_metrics, seed_metrics)
        for g in KILLGATE_GATES
    ]
    assert any(r["killed"] for r in killed), (
        "Probe must kill the identity candidate (win_rate_uplift=0 < 0.10)"
    )


def test_killgate_rejects_no_improvement(tmp_path):
    """A harness identical to seed (uplift=0) must be REJECTED."""
    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_killgate()
    seed_fv = mock_fitness(seed_harness()).replace(gens_completed=0)
    probe.register(store, conn, baseline=seed_fv)

    verdict = probe.run(
        subject=seed_fv.replace(gens_completed=1),  # gens=1 BUT no uplift
        baseline=seed_fv,
        store=store,
        conn=conn,
    )
    assert verdict.status == REJECT
    assert "win_rate_uplift" in verdict.killed_gates


def test_killgate_accepts_genuine_improvement(tmp_path):
    """A harness with +15pp win_rate AND battles>0 AND gens>0 must ACCEPT."""
    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_killgate()
    seed_fv = mock_fitness(seed_harness()).replace(gens_completed=0, battles_played=30)
    evolved_fv = seed_fv.replace(
        win_rate=seed_fv.win_rate + 0.15,
        gens_completed=1,
        battles_played=30,
    )
    probe.register(store, conn, baseline=seed_fv)
    verdict = probe.run(
        subject=evolved_fv,
        baseline=seed_fv,
        store=store,
        conn=conn,
    )
    assert verdict.status == ACCEPT
    assert verdict.killed_gates == []


def test_killgate_rejects_zero_battles(tmp_path):
    """battles_played=0 must kill (anti-vacuous gate)."""
    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_killgate()
    seed_fv = mock_fitness(seed_harness()).replace(gens_completed=0, battles_played=30)
    probe.register(store, conn, baseline=seed_fv)

    no_battles = seed_fv.replace(
        win_rate=seed_fv.win_rate + 0.20,  # big uplift, but…
        battles_played=0,                  # …no battles played
        gens_completed=1,
    )
    verdict = probe.run(subject=no_battles, baseline=seed_fv, store=store, conn=conn)
    assert verdict.status == REJECT
    assert "battles_played_gt0" in verdict.killed_gates


def test_killgate_rejects_zero_gens(tmp_path):
    """gens_completed=0 must kill (anti-vacuous gate)."""
    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_killgate()
    seed_fv = mock_fitness(seed_harness()).replace(gens_completed=0, battles_played=30)
    probe.register(store, conn, baseline=seed_fv)

    no_gens = seed_fv.replace(
        win_rate=seed_fv.win_rate + 0.20,  # big uplift, but…
        battles_played=30,
        gens_completed=0,                  # …no gens ran
    )
    verdict = probe.run(subject=no_gens, baseline=seed_fv, store=store, conn=conn)
    assert verdict.status == REJECT
    assert "gens_completed_gt0" in verdict.killed_gates


def test_killgate_tamper_raises(tmp_path):
    """Editing the registered gate spec must raise LockTamperError on run."""
    from bene.kernel.eval.probe import LockTamperError

    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_killgate()
    seed_fv = mock_fitness(seed_harness()).replace(gens_completed=0, battles_played=30)
    probe.register(store, conn, baseline=seed_fv)

    # Tamper: mutate the stored gate spec directly
    conn.execute(
        "UPDATE probe_registry SET gate_spec = ? WHERE name = ?",
        ('[]', PROBE_NAME),
    )
    conn.commit()

    with pytest.raises(LockTamperError):
        probe.run(
            subject=seed_fv.replace(gens_completed=1),
            baseline=seed_fv,
            store=store,
            conn=conn,
        )


def test_evolve_killgate_in_report():
    """evolve_battle_harness killgate_report must contain all required fields."""
    out = evolve_battle_harness(seed_harness(), mock_fitness, n_gen=2, run_seed=11,
                                bus_path=False)
    r = out.killgate_report
    for key in ("verdict", "killed_gates", "gate_results", "best_harness_id",
                "seed_win_rate", "best_win_rate", "uplift",
                "gens_completed", "battles_played"):
        assert key in r, f"killgate_report missing {key!r}"
    assert r["battles_played"] > 0
    assert r["gens_completed"] > 0


# ---------------------------------------------------------------------------
# B4 — SharedLog lineage writer

def test_lineage_writes_to_bus(tmp_path):
    bus = str(tmp_path / "bus.db")
    # bootstrap bus schema
    con = sqlite3.connect(bus)
    # Use the REAL shared_log type CHECK (bene/schema.py) so a disallowed type like
    # 'evolution' would be REJECTED — this proves write_lineage uses an allowed type.
    con.execute(
        "CREATE TABLE IF NOT EXISTS shared_log "
        "(log_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        " position INTEGER NOT NULL, "
        " type TEXT NOT NULL CHECK (type IN "
        "  ('intent','vote','decision','commit','result','abort','policy','mail')), "
        " agent_id TEXT, ref_id TEXT, payload TEXT, "
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    con.commit()
    con.close()

    log_id = write_lineage("run-test-001", {"verdict": "ACCEPT", "uplift": 0.15},
                           bus_path=bus)
    assert log_id is not None  # None if the type were rejected by the CHECK

    con = sqlite3.connect(bus)
    row = con.execute("SELECT type, agent_id, payload FROM shared_log").fetchone()
    assert row[0] == "result"  # allowed type (was 'evolution', which the CHECK rejects)
    assert row[1] == "bene-core"
    data = json.loads(row[2])
    assert data["kind"] == "evolution"  # evolution marker preserved in the payload
    assert data["verdict"] == "ACCEPT"
    con.close()


def test_lineage_silently_fails_on_bad_bus():
    result = write_lineage("run-xyz", {"x": 1}, bus_path="/nonexistent/path/bus.db")
    assert result is None  # non-fatal


# ---------------------------------------------------------------------------
# Integration: genome mutation is deterministic given seed

def test_genome_mutation_deterministic():
    h0 = seed_harness()
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    child_a = h0.mutate(rng_a)
    child_b = h0.mutate(rng_b)
    assert child_a.harness_id != child_b.harness_id  # ULIDs differ (time-based)
    assert child_a.params == child_b.params           # but params are identical


def test_mock_fitness_deterministic():
    h0 = seed_harness()
    fv1 = mock_fitness(h0, run_seed=42)
    fv2 = mock_fitness(h0, run_seed=42)
    assert fv1.win_rate == fv2.win_rate
    assert fv1.battles_played == 30  # never zero


def test_seed_harness_canonical_fields():
    """seed_harness() must exactly match adx_showdown canonical H0 schema."""
    h0 = seed_harness()
    assert h0.harness_id == "H0-seed"
    assert h0.params["aggression"] == 1.0
    assert h0.params["switch_threshold_hp"] == 0.25
    assert h0.params["risk_tolerance"] == 0.5
    assert h0.move_selection_strategy == "max_damage"
    assert h0.tool_policy["allow_switch"] is True
    assert h0.tool_policy["lookahead_depth"] == 1


def test_from_adx_dict_roundtrip():
    """BattleHarness.from_adx_dict() must produce a structurally identical genome."""
    h0 = seed_harness()
    rebuilt = BattleHarness.from_adx_dict(h0.to_dict())
    assert rebuilt.harness_id == h0.harness_id
    assert rebuilt.params == h0.params
    assert rebuilt.tool_policy == h0.tool_policy
    assert rebuilt.move_selection_strategy == h0.move_selection_strategy


def test_mutate_non_finite_guard():
    """mutate() must not produce NaN or inf in params."""
    import math as _math
    h0 = seed_harness()
    rng = random.Random(0)
    for _ in range(50):
        child = h0.mutate(rng)
        for v in child.params.values():
            if isinstance(v, float):
                assert _math.isfinite(v), f"non-finite param: {v}"
