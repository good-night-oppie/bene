"""Contract tests for the SqliteStorage backend.

These exercise the Storage protocol surface and crucially verify the
``idempotency_key`` semantics that Temporal Activity retries depend on.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import ulid

from bene.storage.sqlite import SqliteStorage


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = SqliteStorage(db_path=str(Path(tmp) / "bene-test.db"))
        try:
            yield s
        finally:
            await s.close()


async def test_spawn_and_status(store):
    aid = await store.spawn(name="agent-a")
    info = await store.status(aid)
    assert info["name"] == "agent-a"
    assert info["status"] == "initialized"

    await store.set_status(aid, "running")
    assert (await store.status(aid))["status"] == "running"


async def test_spawn_with_caller_supplied_agent_id(store):
    """Contract: caller-supplied agent_id round-trips intact."""
    pre_allocated = str(ulid.new())
    returned = await store.spawn(name="preallocated-agent", agent_id=pre_allocated)
    assert returned == pre_allocated, (
        "SqliteStorage.spawn must return the caller-supplied agent_id verbatim"
    )

    info = await store.status(returned)
    assert info["name"] == "preallocated-agent"


async def test_spawn_without_agent_id_generates_ulid(store):
    """When agent_id is omitted, a fresh ULID is generated and is unique per call."""
    aid_a = await store.spawn(name="generated-a")
    aid_b = await store.spawn(name="generated-b")
    assert aid_a and aid_b
    assert aid_a != aid_b, "two unspecified-id spawns must yield distinct ULIDs"


async def test_spawn_agent_id_persists_metadata_roundtrip(store):
    """Caller-supplied agent_id must persist alongside the rest of the spawn payload."""
    pre_allocated = str(ulid.new())
    metadata = {"workflow_id": "wf-42", "attempt": 1}
    returned = await store.spawn(
        name="persistent-agent",
        metadata=metadata,
        agent_id=pre_allocated,
    )
    assert returned == pre_allocated

    info = await store.status(pre_allocated)
    assert info["name"] == "persistent-agent"
    assert info["metadata"] == metadata


async def test_spawn_with_agent_id_is_idempotent_on_retry(store):
    """A Temporal Activity replay must observe spawn as a no-op
    when the same agent_id is supplied a second time."""
    pre_allocated = str(ulid.new())
    first = await store.spawn(name="retried-agent", agent_id=pre_allocated)
    second = await store.spawn(name="retried-agent", agent_id=pre_allocated)
    assert first == second == pre_allocated, (
        "spawn must return the existing agent_id on retry, not raise"
    )

    agents = await store.list_agents()
    matching = [a for a in agents if a["agent_id"] == pre_allocated]
    assert len(matching) == 1, "no duplicate agent row should be inserted on retry"


async def test_log_event_idempotency(store):
    aid = await store.spawn(name="event-agent")
    key = "wf-1:step:0:event"

    eid1 = await store.log_event(aid, "agent_step", {"step": 0}, idempotency_key=key)
    eid2 = await store.log_event(aid, "agent_step", {"step": 0}, idempotency_key=key)
    assert eid1 == eid2, "idempotent log_event must return the same event_id on retry"

    events = await store.get_events(aid, event_type="agent_step")
    assert len(events) == 1, "no duplicate event row should be inserted"


async def test_write_file_idempotency(store):
    aid = await store.spawn(name="vfs-agent")
    content_hash, size = await store.blobs.store(b"hello world")
    key = "wf-1:step:0:vfs"

    v1 = await store.write_file(aid, "/note.txt", content_hash, size, idempotency_key=key)
    v2 = await store.write_file(aid, "/note.txt", content_hash, size, idempotency_key=key)
    assert v1 == v2, "idempotent write_file must return the same version"

    h, sz = await store.read_file(aid, "/note.txt")
    assert h == content_hash and sz == size


async def test_tool_call_idempotency(store):
    aid = await store.spawn(name="tool-agent")
    key = "wf-1:step:0:tool"

    cid1 = await store.log_tool_call(aid, "echo", {"x": 1}, idempotency_key=key)
    cid2 = await store.log_tool_call(aid, "echo", {"x": 1}, idempotency_key=key)
    assert cid1 == cid2, "idempotent log_tool_call must return the same call_id"

    await store.complete_tool_call(cid1, {"y": 2})
    calls = await store.get_tool_calls(aid)
    assert len(calls) == 1
    assert calls[0]["status"] == "success"


async def test_state_kv(store):
    aid = await store.spawn(name="kv-agent")
    await store.set_state(aid, "model", "echo")
    assert await store.get_state(aid, "model") == "echo"


async def test_singleton_aliases(store):
    aid = await store.spawn(name="bene-knowledge")
    assert await store.get_singleton("bene-knowledge") == aid
    # Backward-compat alias should resolve too
    assert await store.get_singleton("nonexistent", aliases=("bene-knowledge",)) == aid
