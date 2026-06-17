"""Adapter tests — mirrors when attached, byte-identical legacy when detached."""

from __future__ import annotations

import json
import sqlite3
import statistics
import time

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel.adapters import attach_kernel, genome_from_candidate
from bene.kernel.engrams import DEFER_BUFFER_CAP, ProvenanceRequired
from bene.memory import MemoryStore
from bene.shared_log import SharedLog
from bene.skills import SkillStore

SYS = {"system": "adapter-test"}


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "adapter-test.db"))
    yield b
    b.close()


# ---------------- detached = pure legacy (back-compat) ----------------


def test_detached_memory_writes_no_engrams(db):
    mem = MemoryStore(db.conn)
    agent = db.spawn("legacy-only")
    mid = mem.write(agent, "plain legacy memory", type="insight")
    assert isinstance(mid, int)
    names = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master").fetchall()}
    if "engrams" in names:  # v2 tables may exist from another test db — not here
        n = db.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]
        assert n == 0
    rows = mem.search("legacy memory")
    assert rows and rows[0].content == "plain legacy memory"


def test_detached_skill_and_log_behave_legacy(db):
    skills = SkillStore(db.conn)
    log = SharedLog(db.conn)
    agent = db.spawn("legacy-two")
    sid = skills.save("legacy_skill", "does things", "do {x}")
    assert isinstance(sid, int)
    iid = log.intent(agent, "ship it")
    log.vote(agent, iid, approve=True)
    assert log.tally(iid).approve == 1
    assert not hasattr(log, "weighted_tally")  # added only when attached


# ---------------- attached = mirrors emit engrams ----------------


def test_attached_memory_mirrors_to_engram(db):
    mem = MemoryStore(db.conn)
    handle = attach_kernel(db, memory=mem)
    agent = db.spawn("mirrored")
    mid = mem.write(agent, "postgres uses MVCC for isolation", type="insight", key="pg-mvcc")
    assert isinstance(mid, int)  # legacy return unchanged
    hits = handle.store.search("MVCC", kind="semantic")
    assert hits and hits[0].metadata["mirror"] == "memory"
    assert hits[0].tier == 2  # insight → semantic tier
    # legacy search still works identically
    assert mem.search("MVCC")[0].memory_id == mid


def test_attached_skill_mirrors_to_procedural_engram(db):
    skills = SkillStore(db.conn)
    handle = attach_kernel(db, skills=skills)
    sid = skills.save("review_fastapi", "security review", "Review {target} for risks")
    assert isinstance(sid, int)
    hits = handle.store.search("review_fastapi OR security", kind="procedural")
    assert hits and hits[0].metadata["skill_id"] == sid and hits[0].tier == 3


def test_attached_shared_log_mirrors_intents(db):
    log = SharedLog(db.conn)
    handle = attach_kernel(db, shared_log=log)
    agent = db.spawn("coordinator")
    iid = log.intent(agent, "merge the kernel branch")
    hits = handle.store.search("merge kernel", kind="proposal")
    assert hits and hits[0].metadata["log_id"] == iid
    # votes are NOT mirrored (only coordination-significant entries)
    log.vote(agent, iid, approve=True)
    assert not handle.store.search("vote", kind="proposal")


def test_weighted_tally_added_when_attached(db):
    log = SharedLog(db.conn)
    attach_kernel(db, shared_log=log)
    a1 = db.spawn("voter-1")
    a2 = db.spawn("voter-2")
    iid = log.intent(a1, "proposal X")
    log.vote(a1, iid, approve=True)
    log.vote(a2, iid, approve=False)
    wt = log.weighted_tally(iid)
    assert wt["approve"] == 1 and wt["reject"] == 1
    assert 0.5 <= wt["approve_weighted"] <= 1.0
    # legacy tally untouched
    assert log.tally(iid).approve == 1


def test_attach_is_explicit_optin_per_store(db):
    mem = MemoryStore(db.conn)
    skills = SkillStore(db.conn)
    handle = attach_kernel(db, memory=mem)  # skills NOT attached
    agent = db.spawn("partial")
    mem.write(agent, "mirrored note", type="observation")
    skills.save("unmirrored", "d", "t")
    assert handle.mirrored == ["memory"]
    assert handle.store.search("mirrored note")
    assert not handle.store.search("unmirrored", kind="procedural")


# ---------------- mirror batching (A6) ----------------


def test_mirror_writes_buffer_then_flush_on_read(db):
    """Hot path buffers in memory; any EngramStore read flushes first, so
    read-your-writes through the store API is preserved."""
    mem = MemoryStore(db.conn)
    handle = attach_kernel(db, memory=mem)
    agent = db.spawn("buffered")
    for i in range(3):
        mem.write(agent, f"buffered note {i}", type="observation")
    assert handle.store.pending == 3
    # direct SQL does NOT see buffered rows yet (documented semantics)
    assert db.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0] == 0
    hits = handle.store.search("buffered note")  # triggers flush-before-read
    assert len(hits) == 3 and handle.store.pending == 0
    assert all(h.metadata["mirror"] == "memory" for h in hits)


def test_batched_mirror_lands_intact_after_flush(db):
    """Micro-bench-shaped integrity check: N mirrored writes survive a batched
    flush with the frozen mirror shape (kind/tier/title prefix/metadata)."""
    mem = MemoryStore(db.conn)
    handle = attach_kernel(db, memory=mem)
    agent = db.spawn("batch-integrity")
    ids = [
        mem.write(agent, f"fact number {i} about widget", type="insight", key=f"k{i}")
        for i in range(10)
    ]
    assert handle.flush() == 10
    n = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE json_extract(metadata, '$.mirror') = 'memory'"
    ).fetchone()[0]
    assert n == 10
    hits = handle.store.search("widget", kind="semantic", limit=20)
    assert {h.metadata["memory_id"] for h in hits} == set(ids)
    assert all(h.tier == 2 and h.title.startswith("memory:insight:") for h in hits)


def test_mirror_buffer_cap_autoflushes(db):
    """Reaching DEFER_BUFFER_CAP flushes automatically (without committing) —
    the cap bounds both memory held and the crash-loss window."""
    mem = MemoryStore(db.conn)
    handle = attach_kernel(db, memory=mem)
    agent = db.spawn("capped")
    for i in range(DEFER_BUFFER_CAP + 5):
        mem.write(agent, f"note {i}", type="observation")
    assert handle.store.pending == 5
    assert db.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0] == DEFER_BUFFER_CAP


def test_close_drains_buffer_durably(tmp_path):
    """Nothing lost on clean close: attach_kernel hooks Bene.close() to flush
    the buffer into the close-time commit."""
    path = str(tmp_path / "drain.db")
    b = Bene(path)
    mem = MemoryStore(b.conn)
    attach_kernel(b, memory=mem)
    agent = b.spawn("closer")
    for i in range(7):
        mem.write(agent, f"durable mirror {i}", type="insight")
    b.close()
    b2 = Bene(path)
    assert b2.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0] == 7
    b2.close()


def test_kernel_handle_explicit_flush(db):
    mem = MemoryStore(db.conn)
    handle = attach_kernel(db, memory=mem)
    agent = db.spawn("flusher")
    mem.write(agent, "explicit flush target", type="result")
    assert handle.store.pending == 1
    assert handle.flush() == 1
    assert handle.store.pending == 0
    # flushed row sits in the open transaction (durable at caller's commit)
    assert db.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0] == 1


def test_deferred_append_with_parents_links_on_flush(db):
    """Parent links are buffered alongside rows and inserted after the engrams
    batch (FK-safe order); lineage reads flush first."""
    handle = attach_kernel(db)
    s = handle.store
    parent = s.append("trace", "parent step", "p", provenance=SYS, commit=False, deferred=True)
    child = s.append(
        "trace", "child step", "c", provenance=SYS, parents=[parent], commit=False, deferred=True
    )
    assert s.pending == 2
    ancestors = s.lineage(child)
    assert [a.engram_id for a in ancestors] == [parent]
    assert s.pending == 0


def test_deferred_validation_failures_buffer_nothing(db):
    handle = attach_kernel(db)
    s = handle.store
    with pytest.raises(ValueError, match="unknown engram kind"):
        s.append("vibes", "bad", "x", provenance=SYS, commit=False, deferred=True)
    with pytest.raises(ProvenanceRequired):
        s.append("trace", "anon", "x", provenance={}, commit=False, deferred=True)
    with pytest.raises(ValueError, match="unknown link type"):
        s.append(
            "trace",
            "bad link",
            "x",
            provenance=SYS,
            parents=["01HNOPE00000000000000000000"],
            link_type="causes_vibes",
            commit=False,
            deferred=True,
        )
    assert s.pending == 0


def test_default_append_paths_unbuffered_backcompat(db):
    """Round-2 contract frozen: without deferred=True, both commit modes write
    through to SQLite synchronously — no buffer involved."""
    handle = attach_kernel(db)
    s = handle.store
    e1 = s.append("trace", "immediate durable", "x", provenance=SYS)  # default commit=True
    assert s.pending == 0
    e2 = s.append("trace", "transactional", "y", provenance=SYS, commit=False)
    assert s.pending == 0
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE engram_id IN (?,?)", (e1, e2)
    ).fetchone()[0]
    assert rows == 2


def test_deferred_with_commit_true_is_durable_on_return(db):
    """deferred=True + commit=True flushes and commits before returning —
    cross-connection visibility immediately."""
    handle = attach_kernel(db)
    eid = handle.store.append("trace", "durable now", "z", provenance=SYS, deferred=True)
    assert handle.store.pending == 0
    other = sqlite3.connect(db.db_path)
    try:
        n = other.execute("SELECT COUNT(*) FROM engrams WHERE engram_id = ?", (eid,)).fetchone()[0]
    finally:
        other.close()
    assert n == 1


def test_mirror_overhead_p50_under_lenient_bound(tmp_path):
    """Timing sanity only — lenient 2 ms bound for CI noise. The binding A6
    measurement (gate < 2 x 168.9 us) is the bench harness's job."""

    def p50_write(db_path, attach: bool) -> float:
        b = Bene(str(db_path))
        mem = MemoryStore(b.conn)
        if attach:
            attach_kernel(b, memory=mem)
        agent = b.spawn("timer")
        samples = []
        for i in range(200):
            t0 = time.perf_counter()
            mem.write(agent, f"timing sample body {i}", type="observation")
            samples.append(time.perf_counter() - t0)
        b.close()
        return statistics.median(samples)

    base = p50_write(tmp_path / "base.db", attach=False)
    mirrored = p50_write(tmp_path / "mirror.db", attach=True)
    overhead = mirrored - base
    assert overhead < 0.002, f"mirror overhead p50 {overhead * 1e6:.1f}us >= 2ms"


# ---------------- metaharness bridge ----------------


def test_genome_from_candidate_bridges_fields():
    g = genome_from_candidate({"prompt": "solve carefully", "memory_policy": "selective"})
    assert g.components["prompt"] == "solve carefully"
    assert g.components["memory_policy"] == "selective"
    assert set(g.components) == {
        "memory_policy",
        "retrieval_policy",
        "context_strategy",
        "tool_config",
        "prompt",
    }


def test_genome_from_candidate_falls_back_to_strategy():
    g = genome_from_candidate({"strategy": "plan then act"})
    assert g.components["prompt"] == "plan then act"


# ---------------- demo + first-run UX ----------------


def test_demo_no_ui_runs_clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(cli, ["demo", "--no-ui"])
    assert res.exit_code == 0, res.output
    assert "story complete" in res.output
    assert "ACCEPT" in res.output and "denied" in res.output  # gates + ladder both shown


def test_ls_first_run_guidance_json(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "ls", "--db", str(tmp_path / "nope.db")])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["agents"] == [] and "next_steps" in data
