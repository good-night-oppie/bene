"""Held-out promotion gate (C2 / 防偷懒) — disjointness, margin gate, hash stamp."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import (
    ACCEPT,
    REJECT,
    VOID,
    HeldoutGate,
    HeldoutManifest,
    build_heldout_probe,
    disjoint,
)

HELD = [("ckptA", 1, "s1"), ("ckptA", 2, "s2"), ("ckptB", 3, "s3")]
TRAIN_DISJOINT = [("ckptC", 9, "s9"), ("ckptD", 8, "s8")]
TRAIN_OVERLAP = [("ckptC", 9, "s9"), ("ckptA", 1, "s1")]  # shares HELD[0]


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "heldout-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


def _run_heldout(scores: dict):
    """Fake adx battle.run_heldout: score one agent over the tuples."""

    def run(tuples, agent):
        return scores[agent]

    return run


# ---------------- manifest + disjointness ----------------


def test_manifest_hash_is_order_independent():
    a = HeldoutManifest.of(HELD)
    b = HeldoutManifest.of(list(reversed(HELD)))
    assert a.manifest_hash == b.manifest_hash
    assert a.tuple_hashes == b.tuple_hashes


def test_disjoint_true_and_false():
    held = HeldoutManifest.of(HELD)
    assert disjoint(held, HeldoutManifest.of(TRAIN_DISJOINT))
    assert not disjoint(held, HeldoutManifest.of(TRAIN_OVERLAP))


# ---------------- registration / admissibility ----------------


def test_register_is_admissible_with_positive_margin_and_freezes_manifest(db, store):
    held = HeldoutManifest.of(HELD)
    probe = build_heldout_probe(held, _run_heldout({"inc": 0.6}), margin=0.05)
    HeldoutGate(store, db.conn).register(probe, held, incumbent="inc")
    row = db.conn.execute(
        "SELECT status FROM probe_registry WHERE name = ?", (probe.name,)
    ).fetchone()
    assert row[0] == "admissible"
    # the manifest is frozen as a hash-locked eval engram
    n = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE kind='eval' AND title LIKE 'heldout-manifest:%'"
    ).fetchone()[0]
    assert n == 1


def test_zero_margin_is_inadmissible_and_scores_void(db, store):
    held = HeldoutManifest.of(HELD)
    probe = build_heldout_probe(held, _run_heldout({"inc": 0.6, "cand": 0.9}), margin=0.0)
    gate = HeldoutGate(store, db.conn)
    gate.register(probe, held, incumbent="inc")
    out = gate.score(
        probe, held, candidate="cand", incumbent="inc", training=HeldoutManifest.of(TRAIN_DISJOINT)
    )
    assert out["verdict"].status == VOID  # a gate you cannot fail is not a gate


# ---------------- scoring + the overfit guard ----------------


def test_accept_when_candidate_beats_incumbent_by_margin_and_stamps_three_hashes(db, store):
    held = HeldoutManifest.of(HELD)
    train = HeldoutManifest.of(TRAIN_DISJOINT)
    probe = build_heldout_probe(held, _run_heldout({"inc": 0.6, "cand": 0.7}), margin=0.05)
    gate = HeldoutGate(store, db.conn)
    gate.register(probe, held, incumbent="inc")
    out = gate.score(probe, held, candidate="cand", incumbent="inc", training=train)
    assert out["verdict"].status == ACCEPT
    stamp = out["stamp"]
    assert set(stamp) == {
        "probe_lock_sha256",
        "heldout_manifest_sha256",
        "training_manifest_sha256",
    }
    assert stamp["heldout_manifest_sha256"] == held.manifest_hash
    assert stamp["training_manifest_sha256"] == train.manifest_hash
    # the stamp is persisted as an auditable eval engram
    n = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE kind='eval' AND title LIKE 'heldout-promotion-stamp:%'"
    ).fetchone()[0]
    assert n == 1


def test_reject_when_candidate_does_not_beat_incumbent(db, store):
    held = HeldoutManifest.of(HELD)
    probe = build_heldout_probe(held, _run_heldout({"inc": 0.6, "cand": 0.61}), margin=0.05)
    gate = HeldoutGate(store, db.conn)
    gate.register(probe, held, incumbent="inc")
    out = gate.score(
        probe, held, candidate="cand", incumbent="inc", training=HeldoutManifest.of(TRAIN_DISJOINT)
    )
    assert out["verdict"].status == REJECT and out["stamp"] is None


def test_overfit_guard_voids_without_scoring_when_training_overlaps(db, store):
    """An overfit candidate that scores great but tuned on held-out tuples must be
    VOIDed BEFORE scoring — run_heldout is never called for it."""
    held = HeldoutManifest.of(HELD)
    called = {"n": 0}

    def run(tuples, agent):
        called["n"] += 1
        return 0.99  # would trivially ACCEPT if scored

    probe = build_heldout_probe(held, run, margin=0.05)
    gate = HeldoutGate(store, db.conn)
    gate.register(probe, held, incumbent="inc")  # 1 call (admissibility, incumbent baseline)
    called["n"] = 0  # reset after registration
    out = gate.score(
        probe, held, candidate="cand", incumbent="inc", training=HeldoutManifest.of(TRAIN_OVERLAP)
    )
    assert out["verdict"].status == VOID
    assert "not disjoint" in out["verdict"].reason
    assert out["stamp"] is None
    assert called["n"] == 0  # never scored — overfit data earns no promotion
