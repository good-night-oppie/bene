"""Engram substrate tests — provenance, ladder, lineage, FTS, back-compat."""

from __future__ import annotations

import hashlib

import pytest

from bene import Bene
from bene.kernel import (
    EngramStore,
    ProvenanceRequired,
    TierViolation,
    UnknownEngram,
    ensure_v2,
)

PROV = {"agent_id": "test-agent"}
SYS = {"system": "unit-test"}


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "kernel-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


# ---------------- append / get / payload ----------------


def test_append_and_get_roundtrip(store):
    eid = store.append("trace", "tool call: read_file", "read /src/auth.py", provenance=PROV)
    e = store.get(eid)
    assert e.kind == "trace" and e.tier == 0 and e.title == "tool call: read_file"
    assert e.provenance == PROV


def test_append_requires_provenance(store):
    with pytest.raises(ProvenanceRequired):
        store.append("trace", "anonymous", "no provenance", provenance={})


def test_append_rejects_unknown_kind(store):
    with pytest.raises(ValueError, match="unknown engram kind"):
        store.append("vibes", "nope", "x", provenance=PROV)


def test_system_provenance_accepted(store):
    eid = store.append("report", "sweeper report", "findings: none", provenance=SYS)
    assert store.get(eid).provenance == SYS


def test_small_payload_inlined(store):
    eid = store.append("trace", "small", "tiny body", provenance=PROV)
    e = store.get(eid)
    assert e.inline_body == "tiny body" and e.content_hash is None
    assert store.payload(eid) == b"tiny body"


def test_large_payload_goes_to_blob_store(store):
    big = "x" * 10_000
    eid = store.append("trace", "big", big, provenance=PROV)
    e = store.get(eid)
    assert e.content_hash is not None and e.inline_body is None
    assert store.payload(eid) == big.encode()


def test_get_unknown_raises(store):
    with pytest.raises(UnknownEngram):
        store.get("01HNOPE00000000000000000000")


def test_metadata_roundtrip(store):
    eid = store.append("trace", "meta", "x", provenance=PROV, metadata={"k": [1, 2]})
    assert store.get(eid).metadata == {"k": [1, 2]}


# ---------------- search ----------------


def test_fts_search_finds_by_body(store):
    store.append("trace", "alpha", "the retry bug lives in backoff logic", provenance=PROV)
    store.append("trace", "beta", "unrelated content entirely", provenance=PROV)
    hits = store.search("retry backoff")
    assert len(hits) == 1 and hits[0].title == "alpha"


def test_fts_search_kind_and_agent_filters(store):
    store.append("semantic", "fact", "postgres uses MVCC", tier=2, provenance=PROV, agent_id=None)
    store.append("trace", "raw", "postgres connection refused", provenance=PROV)
    assert all(h.kind == "semantic" for h in store.search("postgres", kind="semantic"))
    assert all(h.kind == "trace" for h in store.search("postgres", kind="trace"))


def test_search_respects_limit(store):
    for i in range(5):
        store.append("trace", f"t{i}", "common needle phrase", provenance=PROV)
    assert len(store.search("needle", limit=3)) == 3


# ---------------- promotion (compression ladder) ----------------


def test_promote_creates_new_linked_engram(store):
    raw = store.append("trace", "raw run", "step1 step2 step3", provenance=PROV)
    epi = store.promote(
        raw, new_tier=1, title="episode: auth refactor", payload="did the steps", provenance=PROV
    )
    e = store.get(epi)
    assert e.kind == "episodic" and e.tier == 1
    parents = store.lineage(epi, direction="ancestors")
    assert raw in [p.engram_id for p in parents]


def test_promote_never_mutates_source(store):
    raw = store.append("trace", "immutable", "original body", provenance=PROV)
    before = store.get(raw)
    store.promote(raw, new_tier=2, title="compressed", payload="summary", provenance=PROV)
    after = store.get(raw)
    assert before == after  # frozen dataclass equality: byte-identical record


def test_promote_requires_higher_tier(store):
    sem = store.append("semantic", "fact", "x", tier=2, provenance=PROV)
    with pytest.raises(TierViolation):
        store.promote(sem, new_tier=2, title="same", payload="y", provenance=PROV)
    with pytest.raises(TierViolation):
        store.promote(sem, new_tier=1, title="down", payload="y", provenance=PROV)


def test_promote_kind_follows_ladder(store):
    raw = store.append("trace", "t", "x", provenance=PROV)
    assert (
        store.get(store.promote(raw, new_tier=3, title="skill", payload="s", provenance=PROV)).kind
        == "procedural"
    )
    assert (
        store.get(store.promote(raw, new_tier=4, title="gene", payload="g", provenance=PROV)).kind
        == "strategic"
    )


def test_promote_multi_source_consolidation(store):
    traces = [store.append("trace", f"t{i}", f"run {i}", provenance=PROV) for i in range(3)]
    skill = store.promote(
        traces[0],
        new_tier=3,
        title="distilled skill",
        payload="do X then Y",
        provenance=PROV,
        sources=traces[1:],
    )
    ancestors = {e.engram_id for e in store.lineage(skill, direction="ancestors")}
    assert set(traces) <= ancestors  # provenance to EVERY source trace


# ---------------- lineage ----------------


def test_lineage_three_generations(store):
    g0 = store.append("trace", "gen0", "raw", provenance=PROV)
    g1 = store.promote(g0, new_tier=1, title="gen1", payload="ep", provenance=PROV)
    g2 = store.promote(g1, new_tier=2, title="gen2", payload="sem", provenance=PROV)
    g3 = store.promote(g2, new_tier=3, title="gen3", payload="skill", provenance=PROV)
    ancestors = [e.engram_id for e in store.lineage(g3, direction="ancestors")]
    assert ancestors == [g2, g1, g0]  # BFS order, 3 generations
    descendants = [e.engram_id for e in store.lineage(g0, direction="descendants")]
    assert descendants == [g1, g2, g3]


def test_lineage_unknown_engram_raises(store):
    with pytest.raises(UnknownEngram):
        store.lineage("01HNOPE00000000000000000000")


def test_link_rejects_unknown_type(store):
    a = store.append("trace", "a", "x", provenance=PROV)
    b = store.append("trace", "b", "y", provenance=PROV)
    with pytest.raises(ValueError, match="unknown link type"):
        store.link(a, b, "causes_vibes")


def test_supersede_marks_and_links(store):
    old = store.append("procedural", "skill v1", "old way", tier=3, provenance=PROV)
    new = store.append("procedural", "skill v2", "new way", tier=3, provenance=PROV)
    store.supersede(old, new)
    assert store.get(old).superseded_by == new
    assert old in [e.engram_id for e in store.lineage(new, direction="ancestors")]


# ---------------- back-compat: legacy schema untouched ----------------


def _schema_rows(conn) -> set[tuple]:
    return set(map(tuple, conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()))


def test_v2_is_additive_legacy_schema_untouched(tmp_path):
    """Opening a pre-existing 0.1.0 db and running ensure_v2 must not alter
    any legacy table, index, or trigger definition — every pre-existing
    sqlite_master row must survive byte-identical (additive-only schema)."""
    b = Bene(str(tmp_path / "legacy.db"))
    agent = b.spawn("legacy-agent")
    b.write(agent, "/notes.md", b"pre-kernel content")
    rows_pre = _schema_rows(b.conn)
    files_before = b.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    ensure_v2(b.conn)
    ensure_v2(b.conn)  # idempotent

    rows_post = _schema_rows(b.conn)
    assert rows_pre <= rows_post  # nothing dropped, nothing redefined
    digest_pre = hashlib.sha256(repr(sorted(rows_pre)).encode()).hexdigest()
    digest_surviving = hashlib.sha256(
        repr(sorted(r for r in rows_post if r in rows_pre)).encode()
    ).hexdigest()
    assert digest_pre == digest_surviving
    assert b.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == files_before
    assert b.read(agent, "/notes.md") == b"pre-kernel content"
    # v2 tables exist now
    names = {r[0] for r in b.conn.execute("SELECT name FROM sqlite_master").fetchall()}
    assert {"engrams", "engram_links", "capabilities", "probe_registry"} <= names
    b.close()


def test_legacy_db_engrams_work_after_upgrade(tmp_path):
    b = Bene(str(tmp_path / "legacy2.db"))
    b.spawn("a1")
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)
    eid = store.append("trace", "post-upgrade", "works", provenance=SYS)
    assert store.get(eid).title == "post-upgrade"
    b.close()
