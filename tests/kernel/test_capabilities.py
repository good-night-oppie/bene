"""Capability registry tests — register/lookup/list/dispatch + denial events."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import (
    AutonomyDenied,
    CapabilityRegistry,
    EventBus,
    UnknownCapability,
    ensure_v2,
)


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "cap-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def registry(db):
    return CapabilityRegistry(db.conn, bus=EventBus())


def test_register_and_lookup(registry):
    registry.register("memory.search", autonomy_level=0, description="read-only search")
    cap = registry.lookup("memory.search")
    assert cap.autonomy_level == 0 and cap.description == "read-only search"


def test_register_persists_to_db(db, registry):
    registry.register("evolve.promote", autonomy_level=4, description="promote candidate")
    row = db.conn.execute(
        "SELECT autonomy_level FROM capabilities WHERE name='evolve.promote'"
    ).fetchone()
    assert row[0] == 4


def test_register_upsert_updates_level(registry):
    registry.register("x", autonomy_level=1, description="v1")
    registry.register("x", autonomy_level=3, description="v2")
    assert registry.lookup("x").autonomy_level == 3


def test_register_rejects_bad_level(registry):
    with pytest.raises(ValueError):
        registry.register("bad", autonomy_level=7, description="nope")


def test_lookup_unknown_raises(registry):
    with pytest.raises(UnknownCapability):
        registry.lookup("ghost")


def test_list_with_max_level_filter(registry):
    registry.register("read", autonomy_level=0, description="r")
    registry.register("write", autonomy_level=2, description="w")
    registry.register("merge", autonomy_level=4, description="m")
    names = [c.name for c in registry.list(max_level=2)]
    assert names == ["read", "write"]


def test_dispatch_calls_handler(registry):
    registry.register("math.add", autonomy_level=0, description="add", handler=lambda a, b: a + b)
    assert registry.dispatch("math.add", "agent-1", 2, 3) == 5


def test_dispatch_denied_raises_and_emits_event(db):
    bus = EventBus()
    denials = []
    bus.subscribe("capability.denied", denials.append)
    registry = CapabilityRegistry(
        db.conn, bus=bus, autonomy_check=lambda agent, cap: cap.autonomy_level <= 1
    )
    registry.register("danger.merge", autonomy_level=3, description="merge", handler=lambda: 1)
    with pytest.raises(AutonomyDenied):
        registry.dispatch("danger.merge", "low-trust-agent")
    assert len(denials) == 1
    assert denials[0]["capability"] == "danger.merge"
    assert denials[0]["required_level"] == 3


def test_dispatch_allowed_under_check(db):
    registry = CapabilityRegistry(db.conn, autonomy_check=lambda a, c: True)
    registry.register("ok.cap", autonomy_level=4, description="ok", handler=lambda: "ran")
    assert registry.dispatch("ok.cap", "any-agent") == "ran"


def test_dispatch_without_handler_raises(registry):
    registry.register("no.handler", autonomy_level=0, description="ref only")
    with pytest.raises(UnknownCapability):
        registry.dispatch("no.handler", "agent-1")


def test_set_autonomy_check_swaps_policy(db):
    registry = CapabilityRegistry(db.conn)
    registry.register("gated", autonomy_level=2, description="g", handler=lambda: "v")
    assert registry.dispatch("gated", "a") == "v"  # default allow
    registry.set_autonomy_check(lambda agent, cap: False)
    with pytest.raises(AutonomyDenied):
        registry.dispatch("gated", "a")
