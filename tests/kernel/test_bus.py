"""Event bus tests — dispatch, isolation, wildcard, journal mirroring."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.events import EventJournal
from bene.kernel import EventBus


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "bus-test.db"))
    yield b
    b.close()


def test_publish_reaches_subscriber():
    bus = EventBus()
    got = []
    bus.subscribe("x.happened", got.append)
    bus.publish("x.happened", {"n": 1})
    assert got == [{"event_type": "x.happened", "agent_id": None, "n": 1}]


def test_publish_only_matching_type():
    bus = EventBus()
    got = []
    bus.subscribe("a", got.append)
    bus.publish("b", {})
    assert got == []


def test_wildcard_subscriber_sees_everything():
    bus = EventBus()
    got = []
    bus.subscribe("*", got.append)
    bus.publish("a", {"i": 1})
    bus.publish("b", {"i": 2})
    assert [e["event_type"] for e in got] == ["a", "b"]


def test_failing_handler_is_isolated():
    bus = EventBus()
    got = []

    def bad(_e):
        raise RuntimeError("boom")

    bus.subscribe("t", bad)
    bus.subscribe("t", got.append)
    bus.publish("t", {"ok": True})  # must not raise
    assert len(got) == 1 and got[0]["ok"] is True


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    got = []
    sub = bus.subscribe("t", got.append)
    bus.unsubscribe(sub)
    bus.publish("t", {})
    assert got == []


def test_multiple_subscribers_all_called():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("t", a.append)
    bus.subscribe("t", b.append)
    bus.publish("t", {"v": 9})
    assert len(a) == 1 and len(b) == 1


def test_journal_mirror_with_agent(db):
    # NB: sqlite3.Connection is callable (adapter shim), so EventJournal's
    # callable() check treats a raw conn as a getter — pass a lambda, as
    # legacy callers do (bene/core.py:43).
    journal = EventJournal(lambda: db.conn)
    bus = EventBus(journal)
    agent = db.spawn("mirrored")
    bus.publish("engram.appended", {"engram_id": "e1"}, agent_id=agent)
    events = journal.get_events(agent)
    types = [e["event_type"] for e in events]
    assert "kernel.engram.appended" in types


def test_no_journal_mirror_without_agent(db):
    journal = EventJournal(lambda: db.conn)
    bus = EventBus(journal)
    before = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    bus.publish("system.tick", {})  # no agent_id -> no FK row, no crash
    after = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before
