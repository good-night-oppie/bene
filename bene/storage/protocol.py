"""Storage protocol — the durability surface every BENE backend must implement.

This protocol is intentionally small and side-effect-free at the type level:
each method is async, takes primitive Python types, and (for writes) accepts
an ``idempotency_key`` so Temporal Activity retries are safe.

The protocol is split into two interfaces:

* :class:`Storage` — agent metadata, VFS records, events, tool calls, state KV,
  checkpoints. Backed by SQLite (single file) or Postgres (per-agent
  partitioned).
* :class:`BlobStore` — content-addressable bytes. Backed by an SQLite ``blobs``
  table or by S3/MinIO/local filesystem in production.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class BlobStore(Protocol):
    """Content-addressable byte store.

    Implementations MUST be idempotent on ``store`` — storing the same bytes
    twice MUST return the same content hash.
    """

    async def store(self, content: bytes) -> tuple[str, int]:
        """Persist bytes. Returns ``(content_hash, size_bytes)``."""

    async def retrieve(self, content_hash: str) -> bytes:
        """Read bytes by content hash. Raises ``KeyError`` if not present."""

    async def exists(self, content_hash: str) -> bool:
        """Return True if the hash is present."""


@runtime_checkable
class Storage(Protocol):
    """The full durability surface for a BENE deployment.

    Every write method accepts an optional ``idempotency_key``. When supplied,
    a second call with the same ``(agent_id, idempotency_key)`` MUST be a
    no-op and return the same result (event_id, version, etc.) as the first.
    """

    # ── Agent lifecycle ──────────────────────────────────────────────

    async def spawn(
        self,
        name: str,
        config: dict | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
        agent_id: str | None = None,
    ) -> str:
        """Create a new agent and return its ``agent_id``."""

    async def set_status(
        self,
        agent_id: str,
        status: str,
        pid: int | None = None,
    ) -> None: ...

    async def status(self, agent_id: str) -> dict: ...

    async def list_agents(self, status_filter: str | None = None) -> list[dict]: ...

    async def heartbeat(self, agent_id: str) -> None: ...

    async def get_singleton(
        self,
        name: str,
        aliases: Sequence[str] = (),
    ) -> str | None: ...

    # ── VFS ──────────────────────────────────────────────────────────

    async def write_file(
        self,
        agent_id: str,
        path: str,
        content_hash: str,
        size: int,
        idempotency_key: str | None = None,
    ) -> int:
        """Insert a file row pointing at ``content_hash``. Returns version."""

    async def read_file(self, agent_id: str, path: str) -> tuple[str, int]:
        """Return the latest ``(content_hash, size)`` for ``path``."""

    async def delete_file(self, agent_id: str, path: str) -> None: ...

    async def ls(self, agent_id: str, path: str = "/") -> list[dict]: ...

    async def stat(self, agent_id: str, path: str) -> dict: ...

    async def exists(self, agent_id: str, path: str) -> bool: ...

    # ── Append-only event journal ────────────────────────────────────

    async def log_event(
        self,
        agent_id: str,
        event_type: str,
        payload: dict | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Append an event row. Returns ``event_id`` (existing one on retry)."""

    async def get_events(
        self,
        agent_id: str,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]: ...

    # ── Tool call tracking ───────────────────────────────────────────

    async def log_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        input_data: dict,
        parent_call_id: str | None = None,
        call_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Record a tool call start. Returns ``call_id``."""

    async def complete_tool_call(
        self,
        call_id: str,
        output: dict,
        status: str = "success",
        token_count: int | None = None,
        error_message: str | None = None,
    ) -> None: ...

    async def get_tool_calls(
        self,
        agent_id: str,
        limit: int = 100,
    ) -> list[dict]: ...

    # ── State KV ─────────────────────────────────────────────────────

    async def get_state(self, agent_id: str, key: str) -> Any: ...

    async def set_state(self, agent_id: str, key: str, value: Any) -> None: ...

    async def delete_state(self, agent_id: str, key: str) -> None: ...

    # ── Checkpoints ──────────────────────────────────────────────────

    async def checkpoint(
        self,
        agent_id: str,
        label: str | None = None,
    ) -> str:
        """Capture a checkpoint and return its ``checkpoint_id``."""

    async def list_checkpoints(self, agent_id: str) -> list[dict]: ...

    # ── Lifecycle ────────────────────────────────────────────────────

    async def close(self) -> None: ...
