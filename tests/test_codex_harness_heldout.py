"""SECH held-out anti-overfit gate (防偷懒) — bene-core.

Covers the held-out disjointness gate wired into evolve_codex_harness:
  - HeldoutManifest is content-addressed, canonical (order-independent), hash-stable
  - is_disjoint / overlap predicates
  - a DISJOINT held-out manifest is admissible -> normal ACCEPT + the 3 stamped hashes
  - an OVERLAPPING manifest -> VOID (inadmissible eval, distinct from REJECT)
  - omitting the manifest preserves the original behavior (no hash stamps)
"""

from __future__ import annotations

from bene.kernel.codex_harness import (
    HeldoutManifest,
    evolve_codex_harness,
    is_disjoint,
    mock_codex_eval,
    mock_refiner,
    overlap,
    seed_codex_harness,
)
from bene.kernel.eval.verdict import ACCEPT

VOID = "VOID"


# ---------------------------------------------------------------------------
# HeldoutManifest

def test_manifest_hash_is_canonical_and_stable():
    a = HeldoutManifest.from_tuples([("t", 1, "s0"), ("t", 1, "s1")])
    b = HeldoutManifest.from_tuples([("t", 1, "s1"), ("t", 1, "s0")])  # reversed
    c = HeldoutManifest.from_tuples([("t", 1, "s1"), ("t", 1, "s0"), ("t", 1, "s0")])  # dup
    assert a.manifest_hash() == b.manifest_hash() == c.manifest_hash()
    assert len(a) == 2
    assert len(a.manifest_hash()) == 64


def test_disjoint_and_overlap():
    train = HeldoutManifest.from_tuples([("train", 7, "s0"), ("train", 7, "s1")])
    held_disjoint = HeldoutManifest.from_tuples([("heldout", 7, "h0")])
    held_overlap = HeldoutManifest.from_tuples([("train", 7, "s0")])
    assert is_disjoint(held_disjoint, train) is True
    assert is_disjoint(held_overlap, train) is False
    assert len(overlap(held_overlap, train)) == 1
    assert len(overlap(held_disjoint, train)) == 0


# ---------------------------------------------------------------------------
# evolve_codex_harness + held-out gate

def test_disjoint_heldout_is_admissible_and_stamps_hashes():
    # mock training tuples are ("train", run_seed, "scenarioN"); a held-out manifest on
    # a different task id stays disjoint -> admissible -> the win-rate gate runs.
    held = HeldoutManifest.from_tuples([("heldout", 11, f"h{i}") for i in range(5)])
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, heldout_manifest=held, bus_path=False,
    )
    r = out.killgate_report
    assert r["verdict"] == ACCEPT
    # all three hashes stamped (post-hoc provable provenance)
    assert len(r["probe_lock_sha256"]) == 64
    assert r["heldout_manifest_sha256"] == held.manifest_hash()
    assert len(r["training_manifest_sha256"]) == 64
    assert "heldout_overlap_count" not in r  # only set on VOID


def test_overlapping_heldout_voids():
    # A held-out manifest that includes a tuple the mock eval trained on -> VOID.
    held = HeldoutManifest.from_tuples([("train", 11, "scenario0"), ("heldout", 11, "h0")])
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, heldout_manifest=held, bus_path=False,
    )
    r = out.killgate_report
    assert r["verdict"] == VOID
    assert r["killed_gates"] == ["heldout_disjointness"]
    assert r["heldout_overlap_count"] >= 1
    # the three provenance hashes are stamped even on VOID
    assert r["heldout_manifest_sha256"] == held.manifest_hash()


def test_no_manifest_preserves_original_behavior():
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, bus_path=False,
    )
    r = out.killgate_report
    assert r["verdict"] == ACCEPT
    assert "probe_lock_sha256" not in r
    assert "heldout_manifest_sha256" not in r


# ---------------------------------------------------------------------------
# VOID on empty manifests — a held-out gate can't prove anything vacuously (PR #65 review)

def test_empty_heldout_manifest_voids():
    """An empty held-out manifest proves nothing -> VOID, never a silent pass."""
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, mock_codex_eval,
        n_gen=3, run_seed=11, heldout_manifest=HeldoutManifest.from_tuples([]),
        bus_path=False,
    )
    r = out.killgate_report
    assert r["verdict"] == VOID
    assert r["killed_gates"] == ["empty_heldout_manifest"]


def test_empty_training_manifest_voids():
    """A Contract-E adapter reporting NO training tuples makes disjointness vacuous
    -> VOID (can't prove 'scored on data it never trained on')."""
    def no_training_eval(harness, run_seed=0, n_battles=30):
        ev = mock_codex_eval(harness, run_seed, n_battles)
        ev.training_tuples = []  # adapter reports nothing it trained on
        return ev

    held = HeldoutManifest.from_tuples([("heldout", 11, f"h{i}") for i in range(5)])
    out = evolve_codex_harness(
        seed_codex_harness(), mock_refiner, no_training_eval,
        n_gen=3, run_seed=11, heldout_manifest=held, bus_path=False,
    )
    r = out.killgate_report
    assert r["verdict"] == VOID
    assert r["killed_gates"] == ["empty_training_manifest"]


def test_void_branch_persists_a_verdict(tmp_path):
    """The voided branch bypasses probe.run(), so it must persist the VOID itself —
    otherwise the run is VOID in killgate_report but absent from experiment_runs /
    eval engrams, and `bene experiments ls` misses it (PR #66 review)."""
    import sqlite3

    db = str(tmp_path / "eval.db")
    out = evolve_codex_harness(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        n_gen=3,
        run_seed=11,
        heldout_manifest=HeldoutManifest.from_tuples([]),  # empty -> VOID branch
        db_path=db,
        bus_path=False,
    )
    assert out.killgate_report["verdict"] == VOID

    # The verdict must be a first-class persisted record, not only a dict field:
    # experiment_runs is exactly what `bene experiments ls` reads.
    con = sqlite3.connect(db)
    runs = con.execute("SELECT summary FROM experiment_runs WHERE kind = 'probe'").fetchall()
    con.close()
    assert any("-> VOID" in (s[0] or "") for s in runs), runs
