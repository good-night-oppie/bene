"""Hardening tests — edge cases the kernel must survive (phase 10)."""

from __future__ import annotations

import threading

import pytest

from bene import Bene
from bene.kernel import (
    EngramStore,
    ProvenanceRequired,
    UnknownEngram,
    ensure_v2,
)
from bene.kernel.eval import LockTamperError, Probe
from bene.kernel.trust import TrustLedger

PROV = {"agent_id": "hardening"}


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "hard.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


# 1. empty db kernel init (no agents, nothing) — all surfaces behave


def test_empty_db_surfaces_clean(tmp_path):
    b = Bene(str(tmp_path / "empty.db"))
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)
    assert store.search("anything") == []
    assert TrustLedger(b.conn, store).summary("ghost-agent")["composite"] >= 0.0
    b.close()


# 2. missing provenance rejected (the no-anonymous-experience invariant)


def test_missing_and_malformed_provenance_rejected(store):
    with pytest.raises(ProvenanceRequired):
        store.append("trace", "t", "x", provenance={})
    with pytest.raises(ProvenanceRequired):
        store.append("trace", "t", "x", provenance={"agent_id": ""})
    with pytest.raises(ProvenanceRequired):
        store.append("trace", "t", "x", provenance=None)  # type: ignore[arg-type]


# 3. concurrent engram writes from two threads (WAL) — no corruption


def test_concurrent_writes_two_threads(tmp_path):
    path = str(tmp_path / "conc.db")
    Bene(path).close()  # create schema
    errors: list[Exception] = []
    N = 25

    def writer(tag: str):
        try:
            b = Bene(path)
            ensure_v2(b.conn)
            s = EngramStore(b.conn, b.blobs)
            for i in range(N):
                s.append("trace", f"{tag}-{i}", f"payload {tag} {i}", provenance=PROV)
            b.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    b = Bene(path)
    n = b.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]
    integrity = b.conn.execute("PRAGMA integrity_check").fetchone()[0]
    b.close()
    assert n == 2 * N and integrity == "ok"


# 4. corrupt/edited lock hash refused


def test_corrupt_lock_hash_refused(db, store):
    gate = {
        "name": "G",
        "description": "d",
        "metric": "q",
        "op": ">=",
        "threshold": 0.1,
        "relative_to_baseline": True,
    }
    p = Probe("hard-probe", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5})
    db.conn.execute("UPDATE probe_registry SET lock_sha256 = 'deadbeef' WHERE name='hard-probe'")
    db.conn.commit()
    with pytest.raises(LockTamperError):
        p.run({"q": 0.9}, {"q": 0.5}, store=store, conn=db.conn)


# 5. oversized payload handled via blob store (content-addressed, retrievable)


def test_oversized_payload_roundtrip(store):
    big = b"\x00binary\xff" * 700_000  # ~5.6MB, non-UTF8
    eid = store.append("trace", "huge", big, provenance=PROV)
    e = store.get(eid)
    assert e.content_hash is not None
    assert store.payload(eid) == big


# 6. FTS query with special characters — clean error or empty, never crash


def test_fts_special_chars_do_not_crash(store):
    """Malformed FTS5 syntax degrades to sanitized search — never an exception."""
    store.append("trace", "normal", "searchable text here", provenance=PROV)
    store.append("trace", "hyphenated", "a-b search token", provenance=PROV)
    for q in ['"unbalanced', "a-b", "x AND", "(((", "NEAR/3", "*", "!!!"]:
        store.search(q)  # must not raise
    # sanitized retry still finds real content
    assert store.search('"searchable text')  # unbalanced quote -> bag-of-words hit
    assert store.search("a-b")  # hyphenated literal -> quoted phrase fallback


# 7. trust summary for nonexistent agent — clean, vacuous, no exception


def test_trust_summary_nonexistent_agent(db, store):
    s = TrustLedger(db.conn, store).summary("never-spawned")
    assert s["composite"] >= 0.0
    assert set(s["signals"]) == {
        "verification_coverage",
        "audit_completeness",
        "checkpoint_discipline",
        "outcome_reliability",
    }


# bonus: lineage on unknown engram raises cleanly; supersede unknown raises


def test_unknown_engram_operations_raise_cleanly(store):
    with pytest.raises(UnknownEngram):
        store.lineage("01HNOPE00000000000000000000")
    with pytest.raises(UnknownEngram):
        store.supersede("01HNOPE00000000000000000000", "01HNOPE00000000000000000001")


# 8. verifier isolation (KERNEL-SPEC invariant 9 — AEVO: no shared state
#    between the evolver and the probe judge; the evolver must be unable to
#    mint its own ACCEPT verdicts)


def test_verifier_isolation_evolver_cannot_mint_verdicts(db, store):
    from bene.kernel.evolve import Genome, PromotionBlocked, ReflectiveEvolver, promote

    seed = Genome(
        components={
            "memory_policy": "a",
            "retrieval_policy": "b",
            "context_strategy": "c",
            "tool_config": "d",
            "prompt": "solve",
        }
    )
    evolver = ReflectiveEvolver(
        store,
        db.conn,
        reflect_fn=lambda g, fb: {
            "component": "prompt",
            "new_text": g.components["prompt"] + "!",
            "rationale": "x",
        },
        benchmark=lambda g: {"quality": 0.5, "cost": 0.1, "tokens": 1.0},
    )
    frontier = evolver.run(seed, generations=2, population=2)

    # The evolver ran a full loop yet produced ZERO eval-kind engrams —
    # verdicts can only enter through the probe layer (separate object,
    # separate code path, no shared mutable state with the evolver).
    n_eval = db.conn.execute("SELECT COUNT(*) FROM engrams WHERE kind='eval'").fetchone()[0]
    assert n_eval == 0
    # And none of its candidates can be promoted without that layer.
    for member in frontier.members():
        if member.engram_id:
            with pytest.raises(PromotionBlocked):
                promote(member.engram_id, store=store, conn=db.conn)
    # promote() itself is read-only over verdict links: still zero eval engrams.
    assert db.conn.execute("SELECT COUNT(*) FROM engrams WHERE kind='eval'").fetchone()[0] == 0
