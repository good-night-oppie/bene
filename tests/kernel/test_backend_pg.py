"""PgEngramConnection — the engram half on real Postgres, EngramStore untouched.

Runs against a local dev Postgres (BENE_TEST_PG_DSN, default the adx-pg
container on :55432) and skips cleanly when unreachable. The point of every
test here: ``engrams.py``/``events.py`` run VERBATIM — only the connection
object changes — and the dialect adapter preserves their contracts (lastrowid,
INSERT OR IGNORE dedupe, FTS lower==better scores, malformed-search degrade).
"""

from __future__ import annotations

import os
import uuid

import pytest

from bene.events import EventJournal
from bene.kernel.backend import PgEngramConnection
from bene.kernel.engrams import EngramStore

ADMIN_DSN = os.environ.get("BENE_TEST_PG_DSN", "postgresql://postgres:arena@127.0.0.1:55432/arena")
TEST_DB = "bene_backend_test"


def _pg_skip_reason() -> str | None:
    try:
        import asyncio

        import asyncpg

        async def prep() -> None:
            conn = await asyncpg.connect(ADMIN_DSN, timeout=3)
            try:
                await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
            except asyncpg.exceptions.DuplicateDatabaseError:
                pass
            finally:
                await conn.close()

        asyncio.run(prep())
        return None
    except Exception as e:  # noqa: BLE001
        return f"postgres unreachable: {type(e).__name__}"


_SKIP = _pg_skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=str(_SKIP))


@pytest.fixture()
def pg_conn():
    dsn = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}"
    conn = PgEngramConnection(dsn)
    # fresh tables per test for repeatability
    conn.execute("DROP TABLE IF EXISTS engram_fts CASCADE")
    conn.execute("DROP TABLE IF EXISTS engram_links CASCADE")
    conn.execute("DROP TABLE IF EXISTS engrams CASCADE")
    conn.execute("DROP TABLE IF EXISTS events CASCADE")
    conn.ensure_schema()
    yield conn
    conn.close()


def _prov(agent: str = "tester") -> dict:
    return {"agent_id": agent, "source": "test_backend_pg"}


def test_engram_append_get_roundtrip(pg_conn):
    store = EngramStore(pg_conn)
    eid = store.append(
        "semantic",
        "retry bug insight",
        "backoff missing jitter",
        provenance=_prov(),
        tier=2,
        agent_id="agentA",
    )
    e = store.get(eid)
    assert e.kind == "semantic" and e.tier == 2 and e.title == "retry bug insight"
    assert e.agent_id == "agentA" and e.created_at  # DB default populated
    assert store.payload(eid) == b"backoff missing jitter"


def test_deferred_flush_and_link_dedupe(pg_conn):
    """flush() drives executemany incl. INSERT OR IGNORE -> ON CONFLICT DO NOTHING."""
    store = EngramStore(pg_conn)
    parent = store.append("trace", "parent", "p", provenance=_prov())
    child = store.append(
        "trace", "child", "c", provenance=_prov(), parents=[parent], deferred=True, commit=False
    )
    assert store.pending == 1
    store.flush(commit=True)
    assert store.pending == 0
    # duplicate link must be ignored, not raise (sqlite INSERT OR IGNORE contract)
    store.link(child, parent, "derived_from")
    ancestors = store.lineage(child, direction="ancestors")
    assert [a.engram_id for a in ancestors] == [parent]


def test_search_scores_keep_fts5_contract(pg_conn):
    """rank = -ts_rank_cd: scores negative, ascending order == best first."""
    store = EngramStore(pg_conn)
    strong = store.append(
        "semantic",
        "jitter jitter jitter",
        "jitter backoff jitter retry jitter",
        provenance=_prov(),
    )
    weak = store.append(
        "semantic", "deploy notes", "one mention of jitter only", provenance=_prov()
    )
    hits = store.search("jitter")
    assert [h.engram_id for h in hits][:2] == [strong, weak]
    scores = [h.score for h in hits]
    assert all(s is not None and s < 0 for s in scores), scores
    assert scores == sorted(scores), "ascending rank order (lower==better) violated"
    # filters thread through the rewritten SQL
    assert store.search("jitter", kind="semantic", limit=1)[0].engram_id == strong
    assert store.search("jitter", kind="procedural") == []


def test_search_malformed_query_degrades_not_crashes(pg_conn):
    store = EngramStore(pg_conn)
    store.append("semantic", "quoted token probe-lock", "probe lock body", provenance=_prov())
    # unbalanced quotes / bare operators — must return a list, never raise
    assert isinstance(store.search('"unbalanced AND ('), list)
    assert isinstance(store.search("AND OR NOT"), list)


def test_event_journal_lastrowid_and_idempotency(pg_conn):
    journal = EventJournal(pg_conn)
    key = f"idem-{uuid.uuid4().hex[:8]}"
    first = journal.log("agentA", "spawned", {"x": 1}, idempotency_key=key)
    assert isinstance(first, int) and first >= 1  # RETURNING event_id shim
    again = journal.log("agentA", "spawned", {"x": 1}, idempotency_key=key)
    assert again == first, "idempotent retry must return the original event_id"
    second = journal.log("agentA", "completed", {})
    assert second > first
    events = journal.get_events("agentA")
    assert len(events) == 2 and journal.count("agentA") == 2
    assert journal.get_latest_event_id("agentA") == second
