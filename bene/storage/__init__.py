"""Pluggable storage backends for BENE.

The :mod:`bene.storage` package decouples the *durability surface* of BENE
(agent registry, VFS, event journal, tool calls, state KV, checkpoints, blob
store) from the in-process :class:`bene.core.Bene` engine.

Backends implement :class:`bene.storage.protocol.Storage` and
:class:`bene.storage.protocol.BlobStore`. Today we ship:

* :class:`bene.storage.sqlite.SqliteStorage` — wraps the existing local-first
  SQLite implementation (zero behavior change).
* :class:`bene.storage.postgres.PostgresStorage` — async Postgres backend
  used by the Temporal worker for horizontally-scalable concurrent agents.

All write methods accept an ``idempotency_key`` so Activities can be safely
retried by Temporal without producing duplicate audit rows.
"""

from bene.storage.protocol import BlobStore, Storage

__all__ = ["Storage", "BlobStore"]
