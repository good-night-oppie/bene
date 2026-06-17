"""Falsifiable-eval layer tests — locks, tamper, admissibility, verdicts."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import (
    ACCEPT,
    REJECT,
    VOID,
    LockTamperError,
    Probe,
    ProbeNotRegistered,
    canonical_spec,
    lock_hash,
)

# A subject here is just a dict of metrics; evaluate_fn is identity-ish.
metrics_fn = dict

IMPROVE_GATE = {
    "name": "G1_quality_improves",
    "description": "quality must improve over baseline by >= 0.05",
    "metric": "quality",
    "op": ">=",
    "threshold": 0.05,
    "relative_to_baseline": True,
}
ABS_FLOOR_GATE = {
    "name": "G2_quality_floor",
    "description": "absolute quality >= 0.5",
    "metric": "quality",
    "op": ">=",
    "threshold": 0.5,
}
UNKILLABLE_GATE = {
    "name": "G_free_pass",
    "description": "always satisfied on identity",
    "metric": "quality",
    "op": ">=",
    "threshold": -999.0,
}

BASELINE = {"quality": 0.6}
BETTER = {"quality": 0.7}
WORSE = {"quality": 0.55}


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "eval-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


def _probe(gates=None, name="quality-probe"):
    return Probe(name, gates or [IMPROVE_GATE, ABS_FLOOR_GATE], metrics_fn)


# ---------------- spec / lock ----------------


def test_canonical_spec_is_order_invariant():
    a = canonical_spec([IMPROVE_GATE, ABS_FLOOR_GATE])
    b = canonical_spec([ABS_FLOOR_GATE, IMPROVE_GATE])
    assert a == b
    assert lock_hash([IMPROVE_GATE, ABS_FLOOR_GATE]) == lock_hash([ABS_FLOOR_GATE, IMPROVE_GATE])


def test_probe_requires_gates():
    with pytest.raises(ValueError, match="at least one gate"):
        Probe("empty", [], metrics_fn)


def test_gate_validation_rejects_bad_op():
    with pytest.raises(ValueError, match="op must be"):
        Probe("bad", [{"name": "g", "metric": "m", "op": "~=", "threshold": 1}], metrics_fn)


# ---------------- registration & admissibility ----------------


def test_register_persists_row_and_lock_engram(db, store):
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    row = db.conn.execute(
        "SELECT status, lock_sha256 FROM probe_registry WHERE name='quality-probe'"
    ).fetchone()
    assert row[0] == "admissible"
    assert row[1] == lock_hash(p.gates)
    locks = store.search('"probe-lock"', kind="eval")  # FTS5: hyphen needs quoting
    assert any("quality-probe" in e.title for e in locks)


def test_admissibility_self_test_kills_identity(db, store):
    """A relative-improvement gate kills the identity candidate -> admissible."""
    p = _probe([IMPROVE_GATE])
    p.register(store, db.conn, baseline=BASELINE)
    status = db.conn.execute(
        "SELECT status FROM probe_registry WHERE name='quality-probe'"
    ).fetchone()[0]
    assert status == "admissible"


def test_unkillable_probe_is_inadmissible_and_void(db, store):
    """A probe whose baseline triggers NO kill gate cannot falsify — VOID."""
    p = _probe([UNKILLABLE_GATE], name="free-pass-probe")
    p.register(store, db.conn, baseline=BASELINE)
    status = db.conn.execute(
        "SELECT status FROM probe_registry WHERE name='free-pass-probe'"
    ).fetchone()[0]
    assert status == "inadmissible"
    # a VOID verdict engram was recorded at registration
    voids = [
        e
        for e in store.search("verdict", kind="eval")
        if e.metadata.get("status") == VOID and e.metadata.get("probe") == "free-pass-probe"
    ]
    assert voids
    # running it yields VOID, never ACCEPT
    v = p.run(BETTER, BASELINE, store=store, conn=db.conn)
    assert v.status == VOID


# ---------------- tamper detection ----------------


def test_tampered_stored_spec_refuses_to_run(db, store):
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    db.conn.execute(
        "UPDATE probe_registry SET gate_spec = replace(gate_spec, '0.05', '0.0001')"
        " WHERE name='quality-probe'"
    )
    db.conn.commit()
    with pytest.raises(LockTamperError, match="does not match its lock"):
        p.run(BETTER, BASELINE, store=store, conn=db.conn)


def test_inmemory_gate_drift_refuses_to_run(db, store):
    """No retune-and-rerun: editing the gates after registration refuses."""
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    p.gates[0]["threshold"] = 0.0001  # retune attempt
    with pytest.raises(LockTamperError, match="differ from the registered"):
        p.run(BETTER, BASELINE, store=store, conn=db.conn)


def test_unregistered_probe_refuses_to_run(db, store):
    with pytest.raises(ProbeNotRegistered):
        _probe().run(BETTER, BASELINE, store=store, conn=db.conn)


# ---------------- verdicts ----------------


def test_accept_on_genuine_improvement(db, store):
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    v = p.run(BETTER, BASELINE, store=store, conn=db.conn)
    assert v.status == ACCEPT and not v.killed_gates
    assert v.engram_id is not None


def test_reject_when_gate_kills(db, store):
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    v = p.run(WORSE, BASELINE, store=store, conn=db.conn)  # only +(-0.05) improvement
    assert v.status == REJECT and "G1_quality_improves" in v.killed_gates


def test_missing_metric_kills(db, store):
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    v = p.run({"other": 1.0}, BASELINE, store=store, conn=db.conn)
    assert v.status == REJECT


def test_verdict_links_to_subject_engram(db, store):
    subject = store.append(
        "strategic", "candidate genome", "policy text", tier=4, provenance={"agent_id": "evo"}
    )
    p = _probe(name="linked-probe")
    p.register(store, db.conn, baseline=BASELINE, subject_ref=subject)
    v = p.run(BETTER, BASELINE, store=store, conn=db.conn)
    assert v.status == ACCEPT
    verifiers = store.lineage(subject, direction="descendants")
    assert v.engram_id in [e.engram_id for e in verifiers]


def test_experiment_run_logged_per_probe_run(db, store):
    p = _probe()
    p.register(store, db.conn, baseline=BASELINE)
    p.run(BETTER, BASELINE, store=store, conn=db.conn)
    p.run(WORSE, BASELINE, store=store, conn=db.conn)
    n = db.conn.execute("SELECT COUNT(*) FROM experiment_runs WHERE kind='probe'").fetchone()[0]
    assert n == 2
    summaries = [r[0] for r in db.conn.execute("SELECT summary FROM experiment_runs").fetchall()]
    assert any("ACCEPT" in s for s in summaries) and any("REJECT" in s for s in summaries)
