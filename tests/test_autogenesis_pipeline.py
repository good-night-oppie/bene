"""Autogenesis engine composition — validate → C2 held-out gate → real kill-gated promote.

Proves the bene engine pieces adx consumes actually compose end-to-end through the
REAL evolve.promote() kill gate (not a stand-in): a valid candidate that beats the
incumbent on a DISJOINT held-out set promotes; an overfit candidate (training
overlap) is VOIDed and cannot promote; an invalid candidate never reaches the gate.
"""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import ACCEPT, VOID, HeldoutGate, HeldoutManifest, build_heldout_probe
from bene.kernel.evolve import PromotionBlocked, promote
from bene.metaharness.harness_store import HarnessEngine

VALID = "def run(problem):\n    return problem\n"
INVALID = "def helper(x):\n    return x\n"  # no run()
HELD = [("ckptA", 1, "s1"), ("ckptA", 2, "s2")]
TRAIN_DISJOINT = [("ckptC", 9, "s9")]
TRAIN_OVERLAP = [("ckptA", 1, "s1")]  # shares HELD[0] — overfit


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "autogen.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


def _candidate(store, src=VALID) -> str:
    return store.append(
        "strategic", "autogen-candidate", src, tier=4, provenance={"system": "autogen-test"}
    )


def _scores(t, agent):
    return {"cand": 0.7, "inc": 0.6}[agent]  # candidate beats incumbent by 0.1


def test_valid_candidate_beating_disjoint_heldout_promotes(db, store):
    # 1. validate (sandboxed AST+smoke) — the candidate is well-formed
    assert HarnessEngine().validate(VALID).ok
    # 2. the candidate as a tier-4 genome engram
    cand = _candidate(store)
    # 3. C2 held-out gate, scored on a set DISJOINT from training
    held = HeldoutManifest.of(HELD)
    probe = build_heldout_probe(held, _scores, margin=0.05)
    gate = HeldoutGate(store, db.conn)
    gate.register(probe, held, incumbent="inc")
    out = gate.score(
        probe,
        held,
        candidate="cand",
        incumbent="inc",
        training=HeldoutManifest.of(TRAIN_DISJOINT),
        subject_ref=cand,
    )
    assert out["verdict"].status == ACCEPT
    # 4. the held-out ACCEPT (probe-backed, verifies→candidate) unlocks the real kill gate
    verdict_id = promote(cand, store=store, conn=db.conn)
    assert verdict_id == out["verdict"].engram_id


def test_overfit_candidate_is_voided_and_cannot_promote(db, store):
    cand = _candidate(store)
    held = HeldoutManifest.of(HELD)
    # would trivially "win" if scored, but it tuned on a held-out tuple
    probe = build_heldout_probe(held, lambda t, a: 0.99, margin=0.05)
    gate = HeldoutGate(store, db.conn)
    gate.register(probe, held, incumbent="inc")
    out = gate.score(
        probe,
        held,
        candidate="cand",
        incumbent="inc",
        training=HeldoutManifest.of(TRAIN_OVERLAP),
        subject_ref=cand,
    )
    assert out["verdict"].status == VOID
    # no probe-backed ACCEPT on record → the kill gate refuses promotion
    with pytest.raises(PromotionBlocked):
        promote(cand, store=store, conn=db.conn)


def test_invalid_candidate_never_reaches_the_gate(db, store):
    res = HarnessEngine().validate(INVALID)
    assert not res.ok and not res.ast_ok  # rejected at validate — pipeline stops here
    # an unvalidated candidate that was never gated cannot promote
    cand = _candidate(store, src=INVALID)
    with pytest.raises(PromotionBlocked):
        promote(cand, store=store, conn=db.conn)
