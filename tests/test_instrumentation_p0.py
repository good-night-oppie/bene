"""Characterization tests for the P0 instrumentation surface — regenerated 2026-06-11.

The original test file was lost to gitingest binary-placeholder corruption.
These tests pin the event-journal + tool-call recording contract that the
trust ledger (bene/kernel/trust.py) and pollution detector depend on: every
agent action leaves a queryable, idempotent, timestamped record.
"""

from __future__ import annotations

import pytest

from bene import Bene
from bene.events import EventJournal


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "instr.db"))
    yield b
    b.close()


# ---------------- event journal ----------------


def test_spawn_emits_lifecycle_event(db):
    agent = db.spawn("instrumented")
    journal = EventJournal(lambda: db.conn)
    types = [e["event_type"] for e in journal.get_events(agent)]
    assert any("spawn" in t or "creat" in t for t in types)


def test_file_write_is_journaled(db):
    agent = db.spawn("writer")
    journal = EventJournal(lambda: db.conn)
    before = journal.count(agent)
    db.write(agent, "/notes.md", b"observable")
    assert journal.count(agent) > before


def test_event_log_idempotency_key_dedupes(db):
    agent = db.spawn("retrier")
    journal = EventJournal(lambda: db.conn)
    e1 = journal.log(agent, "custom.step", {"n": 1}, idempotency_key="step-1")
    e2 = journal.log(agent, "custom.step", {"n": 1}, idempotency_key="step-1")
    assert e1 == e2  # safe Temporal-activity retry semantics


def test_events_are_ordered_and_filterable(db):
    agent = db.spawn("ordered")
    journal = EventJournal(lambda: db.conn)
    journal.log(agent, "alpha", {})
    journal.log(agent, "beta", {})
    events = journal.get_events(agent, limit=5)
    assert events[0]["event_id"] > events[-1]["event_id"]  # DESC order
    only_beta = journal.get_events(agent, event_type="beta")
    assert {e["event_type"] for e in only_beta} == {"beta"}


# ---------------- tool-call recording ----------------


def test_tool_call_lifecycle_recorded(db):
    agent = db.spawn("caller")
    cid = db.log_tool_call(agent, "read_file", {"path": "/x"})
    row = db.conn.execute(
        "SELECT tool_name, status FROM tool_calls WHERE call_id = ?", (cid,)
    ).fetchone()
    assert row == ("read_file", "pending")
    db.complete_tool_call(cid, output={"ok": True}, status="success")
    row = db.conn.execute(
        "SELECT status, output, completed_at FROM tool_calls WHERE call_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "success" and row[1] is not None and row[2] is not None


def test_tool_call_error_status_recorded(db):
    agent = db.spawn("failer")
    cid = db.log_tool_call(agent, "broken_tool", {})
    db.complete_tool_call(cid, output={"err": "boom"}, status="error")
    status = db.conn.execute("SELECT status FROM tool_calls WHERE call_id = ?", (cid,)).fetchone()[
        0
    ]
    assert status == "error"


def test_audit_trail_supports_trust_completeness_query(db):
    """The exact query shape TrustLedger.audit_completeness runs must work."""
    agent = db.spawn("audited")
    c1 = db.log_tool_call(agent, "t", {})
    db.complete_tool_call(c1, output={}, status="success")
    db.log_tool_call(agent, "t", {})  # left pending
    total = db.conn.execute(
        "SELECT COUNT(*) FROM tool_calls WHERE agent_id = ?", (agent,)
    ).fetchone()[0]
    complete = db.conn.execute(
        "SELECT COUNT(*) FROM tool_calls WHERE agent_id = ?"
        " AND status IN ('success','error') AND output IS NOT NULL",
        (agent,),
    ).fetchone()[0]
    assert (total, complete) == (2, 1)


def test_events_payload_roundtrip_json(db):
    agent = db.spawn("payloads")
    journal = EventJournal(lambda: db.conn)
    journal.log(agent, "structured", {"nested": {"k": [1, 2]}})
    e = journal.get_events(agent, event_type="structured")[0]
    assert e["payload"] == {"nested": {"k": [1, 2]}}


def test_timestamps_present_on_all_records(db):
    agent = db.spawn("timed")
    journal = EventJournal(lambda: db.conn)
    journal.log(agent, "tick", {})
    e = journal.get_events(agent, limit=1)[0]
    assert e["timestamp"]
    cid = db.log_tool_call(agent, "t", {})
    started = db.conn.execute(
        "SELECT started_at FROM tool_calls WHERE call_id = ?", (cid,)
    ).fetchone()[0]
    assert started
