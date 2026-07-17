"""Postgres-backed implementation of the :class:`Storage` protocol.

Designed for the distributed/Temporal deployment of BENE:

* No single-writer bottleneck — every Activity runs against a shared pool.
* Concurrent agents are partitioned by ``agent_id`` (hash) — events for
  different agents never contend for the same row lock.
* All write methods accept an ``idempotency_key`` and use ``ON CONFLICT DO
  NOTHING`` for safe Activity retries.

Requires :mod:`asyncpg`. Install with ``pip install 'bene[temporal]'``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

try:
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    asyncpg = None  # type: ignore

import ulid

from bene.storage.protocol import BlobStore, Storage


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_id       TEXT REFERENCES agents(agent_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'initialized',
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    pid             INTEGER,
    last_heartbeat  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);
CREATE INDEX IF NOT EXISTS idx_agents_created_at_desc_v2 ON agents(created_at DESC);

CREATE TABLE IF NOT EXISTS files (
    file_id          BIGSERIAL PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(agent_id),
    path             TEXT NOT NULL,
    is_dir           BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash     TEXT,
    size             BIGINT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    modified_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    version          INTEGER NOT NULL DEFAULT 1,
    deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_key  TEXT,
    UNIQUE(agent_id, path, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_files_idem
    ON files(agent_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_files_agent_path
    ON files(agent_id, path) WHERE deleted = FALSE;

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id          TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(agent_id),
    tool_name        TEXT NOT NULL,
    input            JSONB NOT NULL,
    output           JSONB,
    status           TEXT NOT NULL DEFAULT 'pending',
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    duration_ms      INTEGER,
    token_count      INTEGER,
    parent_call_id   TEXT REFERENCES tool_calls(call_id),
    error_message    TEXT,
    idempotency_key  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_calls_idem
    ON tool_calls(agent_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent ON tool_calls(agent_id, started_at);

CREATE TABLE IF NOT EXISTS state (
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, key)
);

CREATE TABLE IF NOT EXISTS events (
    event_id         BIGSERIAL PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(agent_id),
    event_type       TEXT NOT NULL,
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idem
    ON events(agent_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_agent_time ON events(agent_id, timestamp);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id    TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(agent_id),
    label            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_id         BIGINT,
    file_manifest    JSONB NOT NULL,
    state_snapshot   JSONB NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_agent ON checkpoints(agent_id, created_at);

CREATE TABLE IF NOT EXISTS blobs (
    content_hash  TEXT PRIMARY KEY,
    content       BYTEA NOT NULL,
    ref_count     INTEGER NOT NULL DEFAULT 1
);
"""


class PostgresBlobStore(BlobStore):
    """Stores blobs in a Postgres ``blobs`` table.

    Production deployments should swap this for an S3-backed store; this
    implementation exists so the docker-compose MVP runs end-to-end without
    extra services.
    """

    def __init__(self, pool: "asyncpg.Pool"):
        self._pool = pool

    async def store(self, content: bytes) -> tuple[str, int]:
        h = hashlib.sha256(content).hexdigest()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO blobs (content_hash, content) VALUES ($1, $2) "
                "ON CONFLICT (content_hash) "
                "DO UPDATE SET ref_count = blobs.ref_count + 1",
                h,
                content,
            )
        return h, len(content)

    async def retrieve(self, content_hash: str) -> bytes:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content FROM blobs WHERE content_hash = $1", content_hash
            )
        if not row:
            raise KeyError(f"Blob not found: {content_hash}")
        return bytes(row["content"])

    async def exists(self, content_hash: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 FROM blobs WHERE content_hash = $1", content_hash)
        return row is not None


class PostgresStorage(Storage):
    """Postgres implementation of the :class:`Storage` protocol."""

    def __init__(self, pool: "asyncpg.Pool"):
        if asyncpg is None:  # pragma: no cover - optional dep
            raise ImportError(
                "asyncpg is required for PostgresStorage. "
                "Install with: pip install 'bene[temporal]'"
            )
        self._pool = pool
        self.blobs = PostgresBlobStore(pool)

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 2, max_size: int = 16) -> "PostgresStorage":
        if asyncpg is None:  # pragma: no cover
            raise ImportError("asyncpg is required for PostgresStorage")
        pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
        store = cls(pool)
        await store._init_schema()
        return store

    async def _init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)

    @staticmethod
    def _normalize_path(path: str) -> str:
        from pathlib import PurePosixPath

        return str(PurePosixPath("/" + path.strip("/")))

    # ── Agent lifecycle ──────────────────────────────────────────────

    async def spawn(
        self,
        name: str,
        config: dict | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
        agent_id: str | None = None,
    ) -> str:
        aid = agent_id or str(ulid.new())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO agents (agent_id, name, parent_id, config, metadata) "
                    "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb) "
                    "ON CONFLICT (agent_id) DO NOTHING",
                    aid,
                    name,
                    parent_id,
                    json.dumps(config or {}),
                    json.dumps(metadata or {}),
                )
                await conn.execute(
                    "INSERT INTO files (agent_id, path, is_dir) VALUES ($1, '/', TRUE) "
                    "ON CONFLICT (agent_id, path, version) DO NOTHING",
                    aid,
                )
                await conn.execute(
                    "INSERT INTO events (agent_id, event_type, payload) "
                    "VALUES ($1, 'agent_spawn', $2::jsonb)",
                    aid,
                    json.dumps({"name": name, "parent_id": parent_id}),
                )
        return aid

    async def set_status(
        self,
        agent_id: str,
        status: str,
        pid: int | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if pid is not None:
                await conn.execute(
                    "UPDATE agents SET status = $1, pid = $2, last_heartbeat = now() "
                    "WHERE agent_id = $3",
                    status,
                    pid,
                    agent_id,
                )
            else:
                await conn.execute(
                    "UPDATE agents SET status = $1 WHERE agent_id = $2",
                    status,
                    agent_id,
                )
            await conn.execute(
                "INSERT INTO events (agent_id, event_type, payload) "
                "VALUES ($1, 'state_change', $2::jsonb)",
                agent_id,
                json.dumps({"field": "status", "to": status}),
            )

    async def status(self, agent_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agents WHERE agent_id = $1", agent_id)
        if not row:
            raise ValueError(f"Agent not found: {agent_id}")
        return dict(row)

    async def list_agents(self, status_filter: str | None = None) -> list[dict]:
        async with self._pool.acquire() as conn:
            if status_filter:
                rows = await conn.fetch(
                    "SELECT agent_id, name, status, created_at FROM agents "
                    "WHERE status = $1 ORDER BY created_at",
                    status_filter,
                )
            else:
                rows = await conn.fetch(
                    "SELECT agent_id, name, status, created_at FROM agents ORDER BY created_at"
                )
        return [dict(r) for r in rows]

    async def heartbeat(self, agent_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE agents SET last_heartbeat = now() WHERE agent_id = $1",
                agent_id,
            )

    async def get_singleton(self, name: str, aliases: Sequence[str] = ()) -> str | None:
        candidates = [name, *aliases]
        async with self._pool.acquire() as conn:
            for cand in candidates:
                row = await conn.fetchrow(
                    "SELECT agent_id FROM agents WHERE name = $1 ORDER BY created_at DESC LIMIT 1",
                    cand,
                )
                if row:
                    return row["agent_id"]
        return None

    # ── VFS ──────────────────────────────────────────────────────────

    async def write_file(
        self,
        agent_id: str,
        path: str,
        content_hash: str,
        size: int,
        idempotency_key: str | None = None,
    ) -> int:
        norm = self._normalize_path(path)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if idempotency_key is not None:
                    existing = await conn.fetchrow(
                        "SELECT version FROM files WHERE agent_id = $1 AND idempotency_key = $2",
                        agent_id,
                        idempotency_key,
                    )
                    if existing:
                        return existing["version"]

                # Soft-delete prior versions
                cur_version = await conn.fetchval(
                    "SELECT MAX(version) FROM files "
                    "WHERE agent_id = $1 AND path = $2 AND deleted = FALSE",
                    agent_id,
                    norm,
                )
                new_version = (cur_version or 0) + 1
                if cur_version is not None:
                    await conn.execute(
                        "UPDATE files SET deleted = TRUE "
                        "WHERE agent_id = $1 AND path = $2 AND deleted = FALSE",
                        agent_id,
                        norm,
                    )

                await conn.execute(
                    "INSERT INTO files (agent_id, path, content_hash, size, version, idempotency_key) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    agent_id,
                    norm,
                    content_hash,
                    size,
                    new_version,
                    idempotency_key,
                )
                return new_version

    async def read_file(self, agent_id: str, path: str) -> tuple[str, int]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content_hash, size FROM files "
                "WHERE agent_id = $1 AND path = $2 AND deleted = FALSE AND is_dir = FALSE "
                "ORDER BY version DESC LIMIT 1",
                agent_id,
                self._normalize_path(path),
            )
        if not row:
            raise FileNotFoundError(f"{agent_id}:{path}")
        return row["content_hash"], row["size"]

    async def delete_file(self, agent_id: str, path: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE files SET deleted = TRUE "
                "WHERE agent_id = $1 AND path = $2 AND deleted = FALSE",
                agent_id,
                self._normalize_path(path),
            )

    async def ls(self, agent_id: str, path: str = "/") -> list[dict]:
        norm = self._normalize_path(path)
        prefix = norm.rstrip("/") + "/" if norm != "/" else "/"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT path, is_dir, size, modified_at, version FROM files "
                "WHERE agent_id = $1 AND deleted = FALSE "
                "AND path LIKE $2 AND path != $3 "
                "AND path NOT LIKE $4 "
                "ORDER BY path",
                agent_id,
                prefix + "%",
                norm,
                prefix + "%/%",
            )
        return [dict(r) for r in rows]

    async def stat(self, agent_id: str, path: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM files "
                "WHERE agent_id = $1 AND path = $2 AND deleted = FALSE "
                "ORDER BY version DESC LIMIT 1",
                agent_id,
                self._normalize_path(path),
            )
        if not row:
            raise FileNotFoundError(f"{agent_id}:{path}")
        return dict(row)

    async def exists(self, agent_id: str, path: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM files WHERE agent_id = $1 AND path = $2 AND deleted = FALSE LIMIT 1",
                agent_id,
                self._normalize_path(path),
            )
        return row is not None

    # ── Events ───────────────────────────────────────────────────────

    async def log_event(
        self,
        agent_id: str,
        event_type: str,
        payload: dict | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            if idempotency_key is not None:
                existing = await conn.fetchrow(
                    "SELECT event_id FROM events WHERE agent_id = $1 AND idempotency_key = $2",
                    agent_id,
                    idempotency_key,
                )
                if existing:
                    return existing["event_id"]

            event_id = await conn.fetchval(
                "INSERT INTO events (agent_id, event_type, payload, idempotency_key) "
                "VALUES ($1, $2, $3::jsonb, $4) RETURNING event_id",
                agent_id,
                event_type,
                json.dumps(payload or {}),
                idempotency_key,
            )
        return event_id

    async def get_events(
        self,
        agent_id: str,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            if event_type:
                rows = await conn.fetch(
                    "SELECT * FROM events WHERE agent_id = $1 AND event_type = $2 "
                    "ORDER BY event_id DESC LIMIT $3",
                    agent_id,
                    event_type,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM events WHERE agent_id = $1 ORDER BY event_id DESC LIMIT $2",
                    agent_id,
                    limit,
                )
        return [dict(r) for r in rows]

    # ── Tool calls ───────────────────────────────────────────────────

    async def log_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        input_data: dict,
        parent_call_id: str | None = None,
        call_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        async with self._pool.acquire() as conn:
            if idempotency_key is not None:
                existing = await conn.fetchrow(
                    "SELECT call_id FROM tool_calls WHERE agent_id = $1 AND idempotency_key = $2",
                    agent_id,
                    idempotency_key,
                )
                if existing:
                    return existing["call_id"]

            cid = call_id or str(ulid.new())
            await conn.execute(
                "INSERT INTO tool_calls "
                "(call_id, agent_id, tool_name, input, status, parent_call_id, idempotency_key) "
                "VALUES ($1, $2, $3, $4::jsonb, 'pending', $5, $6) "
                "ON CONFLICT (call_id) DO NOTHING",
                cid,
                agent_id,
                tool_name,
                json.dumps(input_data),
                parent_call_id,
                idempotency_key,
            )
        return cid

    async def complete_tool_call(
        self,
        call_id: str,
        output: dict,
        status: str = "success",
        token_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE tool_calls SET output = $1::jsonb, status = $2, "
                "completed_at = now(), token_count = $3, error_message = $4 "
                "WHERE call_id = $5",
                json.dumps(output),
                status,
                token_count,
                error_message,
                call_id,
            )

    async def get_tool_calls(self, agent_id: str, limit: int = 100) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM tool_calls WHERE agent_id = $1 ORDER BY started_at DESC LIMIT $2",
                agent_id,
                limit,
            )
        return [dict(r) for r in rows]

    # ── State KV ─────────────────────────────────────────────────────

    async def get_state(self, agent_id: str, key: str) -> Any:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM state WHERE agent_id = $1 AND key = $2",
                agent_id,
                key,
            )
        if not row:
            raise KeyError(f"State key not found: {agent_id}:{key}")
        return json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]

    async def set_state(self, agent_id: str, key: str, value: Any) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO state (agent_id, key, value) "
                "VALUES ($1, $2, $3::jsonb) "
                "ON CONFLICT (agent_id, key) DO UPDATE SET "
                "value = EXCLUDED.value, updated_at = now()",
                agent_id,
                key,
                json.dumps(value),
            )

    async def delete_state(self, agent_id: str, key: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM state WHERE agent_id = $1 AND key = $2",
                agent_id,
                key,
            )

    # ── Checkpoints ──────────────────────────────────────────────────

    async def checkpoint(self, agent_id: str, label: str | None = None) -> str:
        cp_id = str(ulid.new())
        async with self._pool.acquire() as conn:
            files = await conn.fetch(
                "SELECT path, content_hash, size, version FROM files "
                "WHERE agent_id = $1 AND deleted = FALSE AND is_dir = FALSE",
                agent_id,
            )
            state_rows = await conn.fetch(
                "SELECT key, value FROM state WHERE agent_id = $1", agent_id
            )
            event_id = await conn.fetchval(
                "SELECT MAX(event_id) FROM events WHERE agent_id = $1", agent_id
            )
            await conn.execute(
                "INSERT INTO checkpoints "
                "(checkpoint_id, agent_id, label, event_id, file_manifest, state_snapshot) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)",
                cp_id,
                agent_id,
                label,
                event_id,
                json.dumps([dict(r) for r in files], default=str),
                json.dumps({r["key"]: r["value"] for r in state_rows}, default=str),
            )
        return cp_id

    async def list_checkpoints(self, agent_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT checkpoint_id, label, created_at, event_id "
                "FROM checkpoints WHERE agent_id = $1 ORDER BY created_at",
                agent_id,
            )
        return [dict(r) for r in rows]

    # ── Lifecycle ────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._pool.close()
