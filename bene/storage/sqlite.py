"""SQLite-backed implementation of the :class:`bene.storage.Storage` protocol.

This adapter wraps the existing :class:`bene.core.Bene` engine — the one that
ships today — so all current behavior, tests, and on-disk databases keep
working unchanged. Async methods run the underlying synchronous SQLite
operations in a thread pool so they slot into the Temporal Activity model
cleanly.

Use this backend for local-first development, single-laptop demos, and
small-team deployments. For >1 concurrent writer fleet, switch the worker to
:class:`bene.storage.postgres.PostgresStorage`.
"""

from __future__ import annotations

# ai-lint-override: R-II-001 - lazy json/ulid imports in legacy helpers; cleanup tracked separately

import asyncio
import hashlib
from typing import Any, Sequence

from bene.core import Bene
from bene.storage.protocol import BlobStore, Storage


# Idempotency-collision counter: replayed-write observability for the
# case-study crash-recovery metric. Falls back to a no-op stub when
# prometheus_client is not installed so this module remains import-safe in
# minimal environments.
try:
    from prometheus_client import Counter as _PromCounter

    IDEMPOTENCY_HITS_TOTAL = _PromCounter(
        "idempotency_hits_total",
        "Count of log_event writes that hit an existing (agent_id, idempotency_key) row.",
        labelnames=["activity"],
    )
except ImportError:  # pragma: no cover - prometheus_client optional

    class _LocalCounter:
        """In-process counter used when prometheus_client is unavailable.

        Keeps the same labels / inc / collect surface so tests and ad-hoc
        readers see the same shape regardless of whether prometheus is
        installed.
        """

        def __init__(self) -> None:
            self._values: dict[tuple[tuple[str, str], ...], float] = {}

        def labels(self, **kwargs: str) -> "_LabelHandle":
            key = tuple(sorted(kwargs.items()))
            return _LabelHandle(self, key)

        def _inc(self, key: tuple[tuple[str, str], ...], amount: float) -> None:
            self._values[key] = self._values.get(key, 0.0) + amount

        def collect(self) -> list["_LocalMetric"]:
            samples = [
                _LocalSample(
                    name="idempotency_hits_total",
                    labels=dict(key),
                    value=value,
                )
                for key, value in self._values.items()
            ]
            return [_LocalMetric(samples=samples)]

    class _LabelHandle:
        def __init__(
            self,
            counter: "_LocalCounter",
            key: tuple[tuple[str, str], ...],
        ) -> None:
            self._counter = counter
            self._key = key

        def inc(self, amount: float = 1.0) -> None:
            self._counter._inc(self._key, amount)

    class _LocalSample:
        def __init__(self, *, name: str, labels: dict[str, str], value: float) -> None:
            self.name = name
            self.labels = labels
            self.value = value

    class _LocalMetric:
        def __init__(self, *, samples: list[_LocalSample]) -> None:
            self.samples = samples

    IDEMPOTENCY_HITS_TOTAL = _LocalCounter()


class SqliteBlobStore(BlobStore):
    """Async wrapper around :class:`bene.blobs.BlobStore`."""

    def __init__(self, bene: Bene):
        self._bene = bene

    async def store(self, content: bytes) -> tuple[str, int]:
        return await asyncio.to_thread(self._bene.blobs.store, content)

    async def retrieve(self, content_hash: str) -> bytes:
        return await asyncio.to_thread(self._bene.blobs.retrieve, content_hash)

    async def exists(self, content_hash: str) -> bool:
        def _check() -> bool:
            row = self._bene.conn.execute(
                "SELECT 1 FROM blobs WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            return row is not None

        return await asyncio.to_thread(_check)


class SqliteStorage(Storage):
    """SQLite implementation of the :class:`Storage` protocol."""

    def __init__(self, db_path: str = "bene.db", *, bene: Bene | None = None):
        self._bene = bene or Bene(db_path=db_path)
        self.blobs = SqliteBlobStore(self._bene)

    @property
    def bene(self) -> Bene:
        """Return the underlying synchronous engine (for callers that need it)."""
        return self._bene

    # ── Agent lifecycle ──────────────────────────────────────────────

    async def spawn(
        self,
        name: str,
        config: dict | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
        agent_id: str | None = None,
    ) -> str:
        if agent_id is not None:
            existing = await asyncio.to_thread(self._existing_agent_id, agent_id)
            if existing is not None:
                return existing
        return await asyncio.to_thread(
            self._bene.spawn,
            name=name,
            config=config,
            parent_id=parent_id,
            metadata=metadata,
            agent_id=agent_id,
        )

    def _existing_agent_id(self, agent_id: str) -> str | None:
        row = self._bene.conn.execute(
            "SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return row[0] if row else None

    async def set_status(
        self,
        agent_id: str,
        status: str,
        pid: int | None = None,
    ) -> None:
        await asyncio.to_thread(self._bene.set_status, agent_id, status, pid)

    async def status(self, agent_id: str) -> dict:
        return await asyncio.to_thread(self._bene.status, agent_id)

    async def list_agents(self, status_filter: str | None = None) -> list[dict]:
        return await asyncio.to_thread(self._bene.list_agents, status_filter)

    async def heartbeat(self, agent_id: str) -> None:
        await asyncio.to_thread(self._bene.heartbeat, agent_id)

    async def get_singleton(
        self,
        name: str,
        aliases: Sequence[str] = (),
    ) -> str | None:
        return await asyncio.to_thread(self._bene.get_singleton, name, aliases)

    # ── VFS ──────────────────────────────────────────────────────────

    async def write_file(
        self,
        agent_id: str,
        path: str,
        content_hash: str,
        size: int,
        idempotency_key: str | None = None,
    ) -> int:
        def _write() -> int:
            if idempotency_key is not None:
                existing = self._bene.conn.execute(
                    "SELECT version FROM files WHERE agent_id = ? AND idempotency_key = ?",
                    (agent_id, idempotency_key),
                ).fetchone()
                if existing:
                    return existing[0]

            self._bene._assert_agent_exists(agent_id)
            norm_path = self._bene._normalize_path(path)
            self._bene._ensure_parents(agent_id, norm_path)

            current = self._bene.conn.execute(
                "SELECT MAX(version) FROM files WHERE agent_id = ? AND path = ? AND deleted = 0",
                (agent_id, norm_path),
            ).fetchone()
            new_version = (current[0] or 0) + 1
            if current and current[0] is not None:
                self._bene.conn.execute(
                    "UPDATE files SET deleted = 1 WHERE agent_id = ? AND path = ? AND deleted = 0",
                    (agent_id, norm_path),
                )

            self._bene.conn.execute(
                "INSERT INTO files (agent_id, path, content_hash, size, version, idempotency_key) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, norm_path, content_hash, size, new_version, idempotency_key),
            )
            self._bene.conn.commit()
            return new_version

        return await asyncio.to_thread(_write)

    async def read_file(self, agent_id: str, path: str) -> tuple[str, int]:
        def _read() -> tuple[str, int]:
            row = self._bene.conn.execute(
                "SELECT content_hash, size FROM files "
                "WHERE agent_id = ? AND path = ? AND deleted = 0 AND is_dir = 0 "
                "ORDER BY version DESC LIMIT 1",
                (agent_id, self._bene._normalize_path(path)),
            ).fetchone()
            if not row:
                raise FileNotFoundError(f"{agent_id}:{path}")
            return row[0], row[1]

        return await asyncio.to_thread(_read)

    async def delete_file(self, agent_id: str, path: str) -> None:
        await asyncio.to_thread(self._bene.delete, agent_id, path)

    async def ls(self, agent_id: str, path: str = "/") -> list[dict]:
        return await asyncio.to_thread(self._bene.ls, agent_id, path)

    async def stat(self, agent_id: str, path: str) -> dict:
        return await asyncio.to_thread(self._bene.stat, agent_id, path)

    async def exists(self, agent_id: str, path: str) -> bool:
        return await asyncio.to_thread(self._bene.exists, agent_id, path)

    # ── Events ───────────────────────────────────────────────────────

    async def log_event(
        self,
        agent_id: str,
        event_type: str,
        payload: dict | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        def _log() -> tuple[int, bool]:
            collision = False
            if idempotency_key is not None:
                row = self._bene.conn.execute(
                    "SELECT event_id FROM events WHERE agent_id = ? AND idempotency_key = ?",
                    (agent_id, idempotency_key),
                ).fetchone()
                if row is not None:
                    collision = True
            event_id = self._bene.events.log(
                agent_id, event_type, payload, idempotency_key=idempotency_key
            )
            self._bene.conn.commit()
            return event_id, collision

        event_id, collision = await asyncio.to_thread(_log)
        if collision:
            # Replayed idempotent write: surface to the case-study metric so
            # crash/recovery hits aren't silently absorbed by the journal.
            IDEMPOTENCY_HITS_TOTAL.labels(activity=event_type).inc()
        return event_id

    async def get_events(
        self,
        agent_id: str,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._bene.events.get_events, agent_id, event_type, None, limit
        )

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
        def _log() -> str:
            if idempotency_key is not None:
                existing = self._bene.conn.execute(
                    "SELECT call_id FROM tool_calls WHERE agent_id = ? AND idempotency_key = ?",
                    (agent_id, idempotency_key),
                ).fetchone()
                if existing:
                    return existing[0]

            cid = call_id or _generate_call_id(agent_id, tool_name, idempotency_key)
            import json

            self._bene.conn.execute(
                "INSERT INTO tool_calls "
                "(call_id, agent_id, tool_name, input, status, parent_call_id, idempotency_key) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (
                    cid,
                    agent_id,
                    tool_name,
                    json.dumps(input_data),
                    parent_call_id,
                    idempotency_key,
                ),
            )
            self._bene.events.log(
                agent_id,
                "tool_call_start",
                {"call_id": cid, "tool_name": tool_name},
                idempotency_key=(idempotency_key + ":start") if idempotency_key else None,
            )
            self._bene.conn.commit()
            return cid

        return await asyncio.to_thread(_log)

    async def complete_tool_call(
        self,
        call_id: str,
        output: dict,
        status: str = "success",
        token_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._bene.complete_tool_call,
            call_id,
            output,
            status,
            token_count,
            error_message,
        )

    async def get_tool_calls(self, agent_id: str, limit: int = 100) -> list[dict]:
        return await asyncio.to_thread(self._bene.get_tool_calls, agent_id, None, None, limit)

    # ── State KV ─────────────────────────────────────────────────────

    async def get_state(self, agent_id: str, key: str) -> Any:
        return await asyncio.to_thread(self._bene.get_state, agent_id, key)

    async def set_state(self, agent_id: str, key: str, value: Any) -> None:
        await asyncio.to_thread(self._bene.set_state, agent_id, key, value)

    async def delete_state(self, agent_id: str, key: str) -> None:
        await asyncio.to_thread(self._bene.delete_state, agent_id, key)

    # ── Checkpoints ──────────────────────────────────────────────────

    async def checkpoint(self, agent_id: str, label: str | None = None) -> str:
        return await asyncio.to_thread(self._bene.checkpoint, agent_id, label)

    async def list_checkpoints(self, agent_id: str) -> list[dict]:
        return await asyncio.to_thread(self._bene.list_checkpoints, agent_id)

    # ── Lifecycle ────────────────────────────────────────────────────

    async def close(self) -> None:
        await asyncio.to_thread(self._bene.close)


def _generate_call_id(agent_id: str, tool: str, idempotency_key: str | None) -> str:
    """Deterministic call_id when idempotency_key is supplied; ULID otherwise."""
    if idempotency_key is None:
        import ulid

        return str(ulid.new())
    seed = f"{agent_id}|{tool}|{idempotency_key}".encode()
    return hashlib.sha256(seed).hexdigest()[:26]
