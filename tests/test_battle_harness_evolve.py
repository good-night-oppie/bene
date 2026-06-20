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

from bene.kernel.battle.adapters import make_contract3_fitness_fn
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
        (
            "h1",
            {
                "win_rate": 0.6,
                "elo": 1100.0,
                "move_legibility": 0.7,
                "no_forfeit_exploit": 0.9,
                "turn_efficiency": 0.8,
                "battles_played": 30.0,
                "gens_completed": 1.0,
            },
        ),
        (
            "h2",
            {
                "win_rate": 0.5,
                "elo": 900.0,
                "move_legibility": 0.8,
                "no_forfeit_exploit": 0.95,
                "turn_efficiency": 0.9,
                "battles_played": 30.0,
                "gens_completed": 1.0,
            },
        ),
    ]
    from bene.metaharness.harness import EvaluationResult

    results = [EvaluationResult(harness_id=hid, scores=s) for hid, s in results_data]

    pareto = compute_pareto(results, CONTRACT3_OBJECTIVES)
    assert len(pareto.points) >= 1
    for p in pareto.points:
        for dim in CONTRACT3_OBJECTIVES:
            assert dim in p.scores, f"Pareto point missing dim {dim!r}"


def test_evolve_pareto_non_empty():
    out = evolve_battle_harness(seed_harness(), mock_fitness, n_gen=2, run_seed=5, bus_path=False)
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
    killed = [evaluate_gate(g, seed_metrics, seed_metrics) for g in KILLGATE_GATES]
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
        battles_played=0,  # …no battles played
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
        gens_completed=0,  # …no gens ran
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
        ("[]", PROBE_NAME),
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
    out = evolve_battle_harness(seed_harness(), mock_fitness, n_gen=2, run_seed=11, bus_path=False)
    r = out.killgate_report
    for key in (
        "verdict",
        "killed_gates",
        "gate_results",
        "best_harness_id",
        "seed_win_rate",
        "best_win_rate",
        "uplift",
        "gens_completed",
        "battles_played",
    ):
        assert key in r, f"killgate_report missing {key!r}"
    assert r["battles_played"] > 0
    assert r["gens_completed"] > 0


# ---------------------------------------------------------------------------
# B4 — SharedLog lineage writer


def test_lineage_writes_to_bus(tmp_path):
    bus = str(tmp_path / "bus.db")
    # bootstrap bus schema
    con = sqlite3.connect(bus)
    # Use the REAL shared_log schema (bene/schema.py): the type CHECK rejects a disallowed
    # 'evolution' type, AND ref_id is `INTEGER REFERENCES shared_log(log_id)` — a thread/reply
    # FK, so a ULID run_id stuffed there would be malformed and FK-dirty (PR #66 review).
    con.execute(
        "CREATE TABLE IF NOT EXISTS shared_log "
        "(log_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        " position INTEGER NOT NULL, "
        " type TEXT NOT NULL CHECK (type IN "
        "  ('intent','vote','decision','commit','result','abort','policy','mail')), "
        " agent_id TEXT, ref_id INTEGER REFERENCES shared_log(log_id), payload TEXT, "
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    con.commit()
    con.close()

    log_id = write_lineage("run-test-001", {"verdict": "ACCEPT", "uplift": 0.15}, bus_path=bus)
    assert log_id is not None  # None if the type were rejected by the CHECK

    con = sqlite3.connect(bus)
    con.execute("PRAGMA foreign_keys=ON")
    row = con.execute("SELECT type, agent_id, ref_id, payload FROM shared_log").fetchone()
    assert row[0] == "result"  # allowed type (was 'evolution', which the CHECK rejects)
    assert row[1] == "bene-core"
    # ref_id is the INTEGER thread/reply FK, NOT a slot for the ULID run_id (PR #66 review):
    assert row[2] is None
    # FK integrity: a NULL ref_id is FK-clean; the old ULID-in-ref_id row failed this check.
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    data = json.loads(row[3])
    assert data["kind"] == "evolution"  # evolution marker preserved in the payload
    assert data["verdict"] == "ACCEPT"
    assert data["run_id"] == "run-test-001"  # run id lives in the payload, not ref_id
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
    assert child_a.params == child_b.params  # but params are identical


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


# ---------------------------------------------------------------------------
# BENE-BATTLE-INTEGRATE — Contract-2 results + A3 fitness adapter


def _battle_result(n_battles=10, wins_a=6, illegal_moves=0):
    return {
        "winner": "a",
        "battles": [],
        "trace_path": "",
        "raw_dims": {
            "opponent_baseline": "RandomPlayer",
            "n_battles": n_battles,
            "wins_a": wins_a,
            "draws": 0,
            "turns": n_battles * 10,
            "forfeits": 0,
            "illegal_moves": illegal_moves,
            "total_moves": n_battles * 10,
        },
    }


def test_contract3_adapter_maps_results_to_bene_fitness_vector():
    calls = []

    def run_vs_baselines(harness_dict, run_seed, n_battles):
        calls.append((harness_dict, run_seed, n_battles))
        return [
            _battle_result(n_battles=n_battles, wins_a=7),
            _battle_result(n_battles=5, wins_a=2),
        ]

    def multi_dim_fitness(results):
        assert len(results) == 2
        return {
            "win_rate": 0.6,
            "elo": 1120.0,
            "move_legibility": 0.98,
            "no_forfeit_exploit": 1.0,
            "turn_efficiency": 0.9,
        }

    fitness = make_contract3_fitness_fn(
        run_vs_baselines, multi_dim_fitness, run_seed=123, n_battles=9
    )
    fv = fitness(seed_harness())

    assert calls[0][0]["harness_id"] == "H0-seed"
    assert calls[0][1:] == (123, 9)
    assert fv.win_rate == 0.6
    assert fv.elo == 1120.0
    assert fv.battles_played == 14
    assert fv.gens_completed == 0


def test_contract3_adapter_accepts_async_runner():
    async def run_vs_baselines(harness_dict, run_seed, n_battles):
        assert harness_dict["harness_id"] == "H0-seed"
        assert run_seed == 5
        assert n_battles == 3
        return [_battle_result(n_battles=3, wins_a=2)]

    def multi_dim_fitness(results):
        assert results[0]["raw_dims"]["n_battles"] == 3
        return {
            "win_rate": 2 / 3,
            "elo": 1050.0,
            "move_legibility": 1.0,
            "no_forfeit_exploit": 1.0,
            "turn_efficiency": 1.0,
        }

    fitness = make_contract3_fitness_fn(
        run_vs_baselines, multi_dim_fitness, run_seed=5, n_battles=3
    )
    fv = fitness(seed_harness())
    assert fv.win_rate == pytest.approx(2 / 3)
    assert fv.battles_played == 3


def test_evolve_accepts_contract3_adapter():
    def run_vs_baselines(harness_dict, _run_seed, n_battles):
        aggression = float(harness_dict["params"]["aggression"])
        wins = 8 if aggression < 0.9 else 5
        return [_battle_result(n_battles=n_battles, wins_a=wins)]

    def multi_dim_fitness(results):
        raw = results[0]["raw_dims"]
        win_rate = raw["wins_a"] / raw["n_battles"]
        return {
            "win_rate": win_rate,
            "elo": 1000.0 + win_rate * 100.0,
            "move_legibility": 1.0,
            "no_forfeit_exploit": 1.0,
            "turn_efficiency": 1.0,
        }

    fitness = make_contract3_fitness_fn(run_vs_baselines, multi_dim_fitness, n_battles=10)
    out = evolve_battle_harness(
        seed_harness(), fitness, n_gen=1, run_seed=0, candidates_per_gen=6, bus_path=False
    )
    assert out.killgate_report["battles_played"] == 10
    assert out.killgate_report["gens_completed"] == 1
    assert out.lineage[0].candidates[0]["scores"]["win_rate"] in {0.5, 0.8}


# ---------------------------------------------------------------------------
# Review follow-ups (PR #62) — regression tests for 5 confirmed-open bugs
# ---------------------------------------------------------------------------


def test_persistent_db_reregister_is_idempotent(tmp_path):
    """CID 3439622163 — a 2nd evolve run on the same persistent db_path must NOT
    raise sqlite3.IntegrityError on the UNIQUE probe_registry.name."""
    db = str(tmp_path / "persist.db")
    out1 = evolve_battle_harness(
        seed_harness(), mock_fitness, n_gen=1, run_seed=3, db_path=db, bus_path=False
    )
    assert out1.killgate_report["verdict"] in {"ACCEPT", "REJECT", "VOID"}
    # 2nd run on the SAME db — blind re-INSERT would raise IntegrityError here.
    out2 = evolve_battle_harness(
        seed_harness(), mock_fitness, n_gen=1, run_seed=3, db_path=db, bus_path=False
    )
    assert out2.killgate_report["verdict"] in {"ACCEPT", "REJECT", "VOID"}
    # Exactly one probe row was registered (reused, not duplicated).
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM probe_registry WHERE name=?", (PROBE_NAME,)).fetchone()[0]
    con.close()
    assert n == 1


def test_mock_fitness_reproducible_across_processes():
    """CID 3439622167 — mock_fitness must NOT depend on process-salted hash() of
    the per-run ULID. Two structurally identical genomes with different ULIDs
    must score identically (digest is over heritable content, not harness_id)."""
    base = seed_harness()
    # Same heritable content, different harness_id (simulates a fresh-per-run ULID).
    twin = BattleHarness(
        harness_id="DIFFERENT-ULID-xyz",
        system_prompt=base.system_prompt,
        move_selection_strategy=base.move_selection_strategy,
        tool_policy=dict(base.tool_policy),
        params=dict(base.params),
    )
    fv_a = mock_fitness(base, run_seed=42)
    fv_b = mock_fitness(twin, run_seed=42)
    assert fv_a.win_rate == fv_b.win_rate
    assert fv_a.turn_efficiency == fv_b.turn_efficiency
    assert fv_a.no_forfeit_exploit == fv_b.no_forfeit_exploit
    assert fv_a.move_legibility == fv_b.move_legibility


def test_mock_fitness_stable_under_pythonhashseed():
    """CID 3439622167 — same genome under different PYTHONHASHSEED subprocesses
    must yield identical win_rate (proves no builtin-hash() salt leaks in)."""
    import subprocess
    import sys

    snippet = (
        "from bene.kernel.battle.genome import mock_fitness, seed_harness;"
        "print(repr(mock_fitness(seed_harness(), run_seed=42).win_rate))"
    )

    def _run(seed_env: str) -> str:
        env = {"PYTHONHASHSEED": seed_env, "PATH": __import__("os").environ["PATH"]}
        return subprocess.check_output([sys.executable, "-c", snippet], env=env, text=True).strip()

    assert _run("0") == _run("12345")


def test_generation_lineage_parent_is_generation_start(monkeypatch):
    """CID 3439622168 — every sibling in a generation records the
    generation-start parent, even after an earlier sibling promotes."""

    seed = seed_harness()
    # Deterministic fitness: 1st mutant of each batch wins big (forces an
    # in-generation promotion), later siblings are mediocre.
    state = {"n": 0}

    def fitness(h):
        if h.harness_id == seed.harness_id:
            return mock_fitness(seed).replace(win_rate=0.40, battles_played=30)
        state["n"] += 1
        wr = 0.95 if state["n"] % 3 == 1 else 0.10
        return mock_fitness(h).replace(win_rate=wr, battles_played=30)

    out = evolve_battle_harness(seed, fitness, n_gen=1, run_seed=1, bus_path=False)
    cands = out.lineage[0].candidates
    # 1st sibling promotes; the 2nd/3rd must still point at the seed, NOT the
    # promoted 1st sibling.
    parents = {c["parent_id"] for c in cands}
    assert parents == {seed.harness_id}, (
        f"later siblings recorded a promoted sibling as parent: {parents}"
    )


def test_verdict_links_to_persisted_engram_not_harness_id(tmp_path):
    """CID 3439622170 — the kill-gate verdict's subject_ref must be a real
    persisted engram id (store.get works), not a raw harness_id string."""
    from bene.kernel.battle.evolve import _append_harness_engram  # noqa: F401

    db = str(tmp_path / "eng.db")
    out = evolve_battle_harness(
        seed_harness(), mock_fitness, n_gen=2, run_seed=8, db_path=db, bus_path=False
    )
    best_eid = out.killgate_report["best_engram_id"]
    seed_eid = out.killgate_report["seed_engram_id"]
    assert best_eid is not None and seed_eid is not None
    # The engram ids must be real rows (NOT the harness_id strings).
    assert best_eid != out.killgate_report["best_harness_id"]
    store, conn = open_eval_db(db)
    got = store.get(best_eid)  # raises if dangling
    assert got is not None
    # The verdict's verifies/refutes edge must point at the persisted engram.
    n = conn.execute(
        "SELECT COUNT(*) FROM engram_links WHERE dst_id=? AND link_type IN ('verifies','refutes')",
        (best_eid,),
    ).fetchone()[0]
    conn.close()
    assert n >= 1, "verdict did not link verifies/refutes to the persisted engram"


def test_killgate_reuses_cached_best_fv_not_noisy_reeval():
    """CID 3439622176 — the final kill-gate must reuse the cached best_fv from
    selection, NOT re-call the (noisy) fitness_fn. A fitness_fn that returns a
    DIFFERENT value on the post-loop call must not change the gate evidence."""
    seed = seed_harness()
    seen: dict[str, int] = {}

    def fitness(h):
        # Seed: stable low baseline so a mutant can show real uplift.
        if h.harness_id == seed.harness_id:
            return mock_fitness(seed).replace(win_rate=0.40, battles_played=30)
        # Per-harness call counter: the FIRST evaluation of a mutant returns a
        # strong, stable score (drives selection); any SECOND evaluation of the
        # SAME harness returns a POISONED score (win_rate=0.0). If the evolver
        # re-runs fitness_fn on the winner after the loop, the gate sees 0.0.
        n = seen.get(h.harness_id, 0)
        seen[h.harness_id] = n + 1
        wr = 0.80 if n == 0 else 0.0
        return mock_fitness(h).replace(win_rate=wr, battles_played=30)

    out = evolve_battle_harness(seed, fitness, n_gen=1, run_seed=2, bus_path=False)
    # best_fv was 0.80 (uplift 0.40 ≥ 0.10) → ACCEPT. A 2nd noisy re-eval would
    # have returned 0.0 → uplift negative → REJECT.
    assert out.killgate_report["best_win_rate"] == 0.80
    assert out.killgate_report["uplift"] == pytest.approx(0.40)
    assert out.killgate_report["verdict"] == ACCEPT


def test_battle_genome_persisted_at_strategic_tier(tmp_path):
    """CID 3442505534 (PR #82 review) — a BattleHarness genome must be persisted at the
    `strategic` tier (tier 4), like genomes/genes elsewhere on the ladder (ReflectiveEvolver,
    metaharness bridge, the sibling codex_harness lane). A tier-0 `procedural` engram would be
    missed by strategic-genome surfaces even though the verdict links verifies/refutes to it."""
    db = str(tmp_path / "tier.db")
    out = evolve_battle_harness(
        seed_harness(), mock_fitness, n_gen=2, run_seed=8, db_path=db, bus_path=False
    )
    best_eid = out.killgate_report["best_engram_id"]
    seed_eid = out.killgate_report["seed_engram_id"]
    store, conn = open_eval_db(db)
    rows = conn.execute(
        "SELECT kind, tier FROM engrams WHERE engram_id IN (?, ?)", (best_eid, seed_eid)
    ).fetchall()
    conn.close()
    assert rows, "candidate engrams not persisted"
    for kind, tier in rows:
        assert kind == "strategic", f"battle genome at {kind!r} tier, expected strategic"
        assert tier == 4, f"strategic engram at tier {tier}, expected 4"
