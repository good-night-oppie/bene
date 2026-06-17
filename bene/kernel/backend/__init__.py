"""Storage backends for the ENGRAM half of the kernel.

``bene/storage/`` abstracts the VFS half (agents/files/state/checkpoints);
this package does the same for the engram substrate that ``EngramStore`` and
the engram ``EventJournal`` ride. SQLite stays the native default (pass a
plain ``sqlite3.Connection`` exactly as before — zero behavior change);
``PgEngramConnection`` is a drop-in connection for Postgres/Supabase.
"""

from bene.kernel.backend.pg import PG_ENGRAM_SCHEMA, PgEngramConnection

__all__ = ["PG_ENGRAM_SCHEMA", "PgEngramConnection"]
