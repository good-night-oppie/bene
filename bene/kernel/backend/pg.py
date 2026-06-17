"""Postgres backend for the ENGRAM half of the kernel (EngramStore + EventJournal).

Complements ``bene/storage/postgres.py`` (the VFS half — agents/files/state):
this module gives the engram substrate a Postgres home WITHOUT touching
``engrams.py``/``events.py``. The trick is a transparent dialect adapter:
``PgEngramConnection`` is a drop-in for the ``sqlite3.Connection`` surface those
modules actually use (``execute``/``executemany``/``commit``/``close`` returning
cursor-likes), and it owns ALL dialect translation:

- ``?`` placeholders        -> ``$n``
- ``INSERT OR IGNORE``      -> ``INSERT ... ON CONFLICT DO NOTHING``
- events ``lastrowid``      -> ``RETURNING event_id`` captured on the cursor shim
- FTS5 ``engram_fts MATCH`` -> ``tsv @@ websearch_to_tsquery`` with
  ``rank = -ts_rank_cd(...)`` — the sign flip preserves FTS5's lower==better
  score contract AND its ascending ``ORDER BY rank`` (best first); search
  RESULTS may still differ across backends ('english' stemmer != FTS5 porter).
- search errors surface as ``sqlite3.OperationalError`` so the engrams.py
  malformed-query degrade path keeps working unchanged.

Sync facade: asyncpg runs on a dedicated daemon thread's event loop; one
logical connection per PgEngramConnection preserves the deferred-mirror
read-your-writes + "durable at the caller's next commit" contract that pool
checkouts would break. Transaction-mode poolers (Supabase :6543) need
``statement_cache_size=0`` (the default here).

Honesty (CLAIMS-AUDIT): this is append/get/search/lineage/journal coverage
only — no deterministic-replay claims, no plasticity, no scheduler.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import threading

try:  # pragma: no cover - optional dependency
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore

# DDL mirrors bene/kernel/schema_v2.py for the engram tables, translated:
# TEXT created_at keeps the SQLite ISO-ms string shape (string comparisons and
# `since` filters stay order-compatible across backends); engram_fts becomes a
# real table with a generated tsvector; agents-FKs are dropped (the agents
# table belongs to the VFS half and may not exist in an engrams-only database).
PG_ENGRAM_SCHEMA = """
CREATE TABLE IF NOT EXISTS engrams (
    engram_id     TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN
                  ('trace','episodic','semantic','procedural','strategic',
                   'eval','experiment','trust','pollution','intervention',
                   'proposal','spec','report')),
    tier          INTEGER NOT NULL DEFAULT 0 CHECK (tier BETWEEN 0 AND 4),
    title         TEXT NOT NULL,
    content_hash  TEXT,
    inline_body   TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}',
    provenance    TEXT NOT NULL,
    agent_id      TEXT,
    created_at    TEXT NOT NULL DEFAULT
                  to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.MS'),
    superseded_by TEXT REFERENCES engrams(engram_id)
);
CREATE INDEX IF NOT EXISTS idx_engrams_kind   ON engrams(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_agent  ON engrams(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_tier   ON engrams(tier);
CREATE INDEX IF NOT EXISTS idx_engrams_active ON engrams(kind) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS engram_links (
    link_id    TEXT PRIMARY KEY,
    src_id     TEXT NOT NULL REFERENCES engrams(engram_id),
    dst_id     TEXT NOT NULL REFERENCES engrams(engram_id),
    link_type  TEXT NOT NULL CHECK (link_type IN
               ('derived_from','consolidates','verifies','refutes','associates',
                'supersedes','about_agent','gated_by')),
    weight     REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT
               to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.MS'),
    UNIQUE(src_id, dst_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_src ON engram_links(src_id);
CREATE INDEX IF NOT EXISTS idx_links_dst ON engram_links(dst_id);

CREATE TABLE IF NOT EXISTS engram_fts (
    engram_id TEXT PRIMARY KEY REFERENCES engrams(engram_id),
    title     TEXT NOT NULL DEFAULT '',
    body      TEXT NOT NULL DEFAULT '',
    tsv       tsvector GENERATED ALWAYS AS
              (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_engram_fts_tsv ON engram_fts USING gin(tsv);

CREATE TABLE IF NOT EXISTS events (
    event_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT,
    timestamp       TEXT NOT NULL DEFAULT
                    to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.MS')
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idem
    ON events(agent_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_agent_time ON events(agent_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
"""

_FTS_SELECT = re.compile(
    r"bm25\(engram_fts\) AS rank FROM engram_fts"
    r" JOIN engrams e ON e\.engram_id = engram_fts\.engram_id"
    r" WHERE engram_fts MATCH \?"
)


def _qmark_to_dollar(sql: str) -> str:
    out: list[str] = []
    n = 0
    in_str = False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        if ch == "?" and not in_str:
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
    return "".join(out)


def _rewrite(sql: str) -> str:
    s = sql
    if "engram_fts MATCH" in s:
        # FTS5 -> tsvector. rank = NEGATED ts_rank_cd keeps lower==better AND
        # ascending ORDER BY rank == best-first, both inherited from bm25().
        s = _FTS_SELECT.sub(
            "-ts_rank_cd(engram_fts.tsv, websearch_to_tsquery('english', ?)) AS rank"
            " FROM engram_fts JOIN engrams e ON e.engram_id = engram_fts.engram_id"
            " WHERE engram_fts.tsv @@ websearch_to_tsquery('english', ?)",
            s,
        )
    if s.lstrip().upper().startswith("INSERT OR IGNORE"):
        head, rest = s.split("OR IGNORE", 1)
        s = head + rest + " ON CONFLICT DO NOTHING"
    if s.lstrip().upper().startswith("INSERT INTO EVENTS") and "RETURNING" not in s.upper():
        s = s + " RETURNING event_id"
    return _qmark_to_dollar(s)


def _expand_fts_params(sql: str, params: tuple | list) -> tuple:
    """The tsvector rewrite uses the query param TWICE (rank + WHERE)."""
    if "engram_fts MATCH" in sql and params:
        return (params[0], *params)
    return tuple(params)


class _CursorShim:
    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(self, rows: list[tuple], lastrowid: int | None, rowcount: int) -> None:
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class PgEngramConnection:
    """sqlite3.Connection drop-in (the subset EngramStore/EventJournal/BlobStore
    use) backed by one asyncpg connection on a dedicated loop thread."""

    def __init__(self, dsn: str, *, statement_cache_size: int = 0) -> None:
        if asyncpg is None:  # pragma: no cover - optional dep
            raise ImportError("asyncpg is required: pip install 'bene[temporal]'")
        self._dsn = dsn
        self._cache_size = statement_cache_size
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._conn = self._call(self._connect())

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=60)

    async def _connect(self):
        return await asyncpg.connect(self._dsn, statement_cache_size=self._cache_size)

    def ensure_schema(self) -> None:
        self._call(self._conn.execute(PG_ENGRAM_SCHEMA))

    # ---- sqlite3.Connection surface ----

    def execute(self, sql: str, params: tuple | list = ()) -> _CursorShim:
        is_fts = "engram_fts MATCH" in sql
        pg_sql = _rewrite(sql)
        pg_params = _expand_fts_params(sql, params)
        try:
            rows = self._call(self._conn.fetch(pg_sql, *pg_params))
        except Exception as e:  # noqa: BLE001 — map dialect errors below
            if is_fts:
                # preserve the engrams.py malformed-query degrade path
                raise sqlite3.OperationalError(str(e)) from e
            raise
        lastrowid = None
        if pg_sql.rstrip().upper().endswith("RETURNING EVENT_ID") and rows:
            lastrowid = int(rows[0][0])
        return _CursorShim([tuple(r) for r in rows], lastrowid, len(rows))

    def executemany(self, sql: str, rows: list[tuple]) -> _CursorShim:
        pg_sql = _rewrite(sql)
        self._call(self._conn.executemany(pg_sql, [tuple(r) for r in rows]))
        return _CursorShim([], None, len(rows))

    def commit(self) -> None:
        # asyncpg autocommits outside explicit transactions; the sqlite commit()
        # contract ("durable now") already holds — this is a deliberate no-op.
        return

    def close(self) -> None:
        try:
            self._call(self._conn.close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
