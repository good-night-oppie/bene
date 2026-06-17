"""A2A endpoint tests — Agent Card, SharedLog-seated TaskStore, JSON-RPC round-trip.

Requires the ``a2a`` extra (``uv sync --extra a2a``); skipped otherwise, like the
temporal/postgres optional suites.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("a2a", reason="a2a extra not installed")

from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart  # noqa: E402
from a2a.utils import new_task  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from bene import Bene  # noqa: E402
from bene.a2a import SharedLogTaskStore, build_app, build_bene_agent_card  # noqa: E402
from bene.shared_log import SharedLog  # noqa: E402


def _user_msg(text: str, **metadata) -> Message:
    return Message(
        message_id="m-test",
        role=Role.user,
        parts=[Part(root=TextPart(text=text))],
        metadata=metadata or None,
    )


# ---------------- Agent Card ----------------


def test_card_builds_and_serializes():
    card = build_bene_agent_card("http://host:9/")
    assert card.name == "bene"
    assert card.url == "http://host:9/"
    skill_ids = {s.id for s in card.skills}
    assert {"coordinate", "harness.propose", "harness.validate"} <= skill_ids
    data = card.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert data["name"] == "bene" and data["skills"]


# ---------------- TaskStore (durable, seated on bene.db) ----------------


def test_taskstore_roundtrip_is_durable(tmp_path):
    db = str(tmp_path / "a2a.db")
    conn = Bene(db).conn
    store = SharedLogTaskStore(conn)
    task = new_task(_user_msg("hello"))

    async def _drive():
        await store.save(task)
        got = await store.get(task.id)
        assert got is not None and got.id == task.id
        # durability: a fresh store over a fresh connection still sees it
        store2 = SharedLogTaskStore(Bene(db).conn)
        again = await store2.get(task.id)
        assert again is not None and again.id == task.id
        await store.delete(task.id)
        assert await store.get(task.id) is None

    asyncio.run(_drive())


def test_taskstore_get_missing_returns_none(tmp_path):
    store = SharedLogTaskStore(Bene(str(tmp_path / "a2a.db")).conn)
    assert asyncio.run(store.get("nope")) is None


# ---------------- End-to-end JSON-RPC over the Starlette app ----------------


def _post_message(client: TestClient, text: str, **metadata):
    req = SendMessageRequest(id="1", params=MessageSendParams(message=_user_msg(text, **metadata)))
    return client.post("/", json=req.model_dump(mode="json", by_alias=True, exclude_none=True))


def test_endpoint_serves_agent_card(tmp_path):
    app = build_app(str(tmp_path / "a2a.db"), "http://testserver/")
    with TestClient(app) as client:
        r = client.get("/.well-known/agent-card.json")
        assert r.status_code == 200
        assert r.json()["name"] == "bene"


def test_message_send_records_intent_in_sharedlog(tmp_path):
    db = str(tmp_path / "a2a.db")
    app = build_app(db, "http://testserver/")
    with TestClient(app) as client:
        r = _post_message(client, "prune stale checkpoints", agent="adx", kind="intent")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "result" in body, body
    # the coordination content landed durably in SharedLog as an intent
    log = SharedLog(Bene(db).conn)
    intents = log.read(type="intent")
    assert len(intents) == 1
    assert intents[0].agent_id == "adx"
    assert "prune stale checkpoints" in intents[0].payload.get("action", "")


def test_message_send_defaults_to_mail(tmp_path):
    db = str(tmp_path / "a2a.db")
    app = build_app(db, "http://testserver/")
    with TestClient(app) as client:
        r = _post_message(client, "fyi: rebuilt the index", agent="adx")  # no kind -> mail
        assert r.status_code == 200, r.text
    log = SharedLog(Bene(db).conn)
    mails = log.read(type="mail")
    assert len(mails) == 1 and mails[0].agent_id == "adx"
    assert mails[0].payload.get("to") == "bene"


def test_harness_validate_handshake_accepts_good_source(tmp_path):
    db = str(tmp_path / "a2a.db")
    app = build_app(db, "http://testserver/")
    src = "def run(problem):\n    return problem\n"
    with TestClient(app) as client:
        r = _post_message(client, src, agent="adx", kind="harness.validate")
        assert r.status_code == 200, r.text
    log = SharedLog(Bene(db).conn)
    last = log.read(type="mail")[-1]
    assert last.payload.get("kind") == "harness.validate"
    assert last.payload["result"]["ok"] is True


def test_harness_validate_handshake_rejects_bad_source(tmp_path):
    db = str(tmp_path / "a2a.db")
    app = build_app(db, "http://testserver/")
    with TestClient(app) as client:
        r = _post_message(
            client, "def helper(x):\n    return x\n", agent="adx", kind="harness.validate"
        )
        assert r.status_code == 200, r.text
    log = SharedLog(Bene(db).conn)
    last = log.read(type="mail")[-1]
    assert last.payload["result"]["ok"] is False  # no run() -> AST reject
