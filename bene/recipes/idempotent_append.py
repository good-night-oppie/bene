"""Reference helpers for atomic, exactly-once completion on a plain SQLite log.

These are a **substrate-agnostic reference**, not a bene runtime feature: every
function takes a ``sqlite3.Connection`` (or could be ported to a JSONL appender),
never a ``Bene``. Copy them into your own events layer. The pattern they encode:

1. **Idempotent append** — ``SELECT`` by ``idempotency_key`` then ``INSERT``,
   so a replayed write is a no-op returning the prior id (exactly-once).
2. **Ordering inversion** — commit the durable record *before* the externally
   visible side effect, so a crash leaves a recorded-but-pending completion
   (replayable), never an orphan side effect (a "ghost").
3. **Projection rebuild** — fold the durable log on boot to reconstruct in-RAM
   state, fixing the restart-amnesia (`/replay` 404) class.

Durability note: this is substrate-agnostic and needs **no Temporal**. It gives
you exactly-once + ghost-free completion on an ordinary SQLite/JSONL log. It does
NOT add cross-process durability beyond what your storage already provides; bene's
``LocalRuntime`` is explicitly not durable across restart, so do not rely on it
for the durable record — use your own committed log (which is the point here).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

DEFAULT_TABLE = "completions"


def _table_sql(table: str) -> str:
    if not table or not table.replace("_", "").isalnum() or table[0].isdigit():
        raise ValueError(f"invalid table name: {table!r}")
    return f'"{table}"'


def ensure_log(conn: sqlite3.Connection, table: str = DEFAULT_TABLE) -> None:
    """Create the append-only completion log if absent. ``idempotency_key`` is
    UNIQUE — the database enforces exactly-once even under a concurrent racer."""
    table_sql = _table_sql(table)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table_sql} ("
        "  seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  idempotency_key TEXT NOT NULL UNIQUE,"
        "  payload TEXT NOT NULL,"
        "  side_effect_done INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.commit()


def append_once(
    conn: sqlite3.Connection,
    idempotency_key: str,
    payload: Any,
    table: str = DEFAULT_TABLE,
) -> tuple[int, bool]:
    """Append ``payload`` keyed by ``idempotency_key``, exactly once.

    Returns ``(seq, created)``. A first write inserts and returns
    ``(new_seq, True)``; a replay with the same key is a no-op that returns
    ``(prior_seq, False)`` — never a duplicate row. Does not commit; the caller
    controls the transaction boundary (see :func:`complete_in_order`).
    """
    table_sql = _table_sql(table)
    row = conn.execute(
        f"SELECT seq FROM {table_sql} WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if row is not None:
        return row[0], False
    cur = conn.execute(
        f"INSERT INTO {table_sql} (idempotency_key, payload) VALUES (?, ?)",
        (idempotency_key, json.dumps(payload)),
    )
    return int(cur.lastrowid), True


def complete_in_order(
    conn: sqlite3.Connection,
    idempotency_key: str,
    payload: Any,
    side_effect: Callable[[Any], None],
    table: str = DEFAULT_TABLE,
) -> tuple[int, bool]:
    """Durable-record-first completion: append + **commit** the record BEFORE the
    externally visible ``side_effect``.

    A crash after the commit but before/within the side effect leaves a
    recorded-but-pending completion — recoverable by retrying the same key —
    never an orphan side effect with no record. The row is marked done only after
    the side effect returns; a replayed key whose side effect is already done is a
    no-op. The external side effect itself must accept the same idempotency key
    or otherwise be safe to retry after a crash during the call.
    Returns ``(seq, created)``.
    """
    table_sql = _table_sql(table)
    seq, created = append_once(conn, idempotency_key, payload, table)
    conn.commit()  # the durable record is committed FIRST
    done = conn.execute(
        f"SELECT side_effect_done FROM {table_sql} WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()[0]
    if done:
        return seq, created
    side_effect(payload)  # externally visible mutation, after the durable commit
    conn.execute(
        f"UPDATE {table_sql} SET side_effect_done = 1 WHERE idempotency_key = ?",
        (idempotency_key,),
    )
    conn.commit()
    return seq, created


def complete_side_effect_first(
    conn: sqlite3.Connection,
    idempotency_key: str,
    payload: Any,
    side_effect: Callable[[Any], None],
    table: str = DEFAULT_TABLE,
) -> tuple[int, bool]:
    """ANTI-PATTERN, shown for contrast: the side effect happens BEFORE the
    durable commit. A crash in between leaves the side effect with no committed
    record — a ghost. Use :func:`complete_in_order` instead."""
    side_effect(payload)  # mutation first
    seq, created = append_once(conn, idempotency_key, payload, table)
    conn.commit()  # committed LAST — a crash before here leaves a ghost
    return seq, created


def replay_projection(
    conn: sqlite3.Connection,
    apply: Callable[[str, Any], None],
    table: str = DEFAULT_TABLE,
) -> int:
    """Rebuild in-RAM state on boot by folding the committed log in ``seq`` order.

    Fixes the restart-amnesia class (a volatile counter / cache lost on restart):
    the durable log is the source of truth; the projection is derived. Returns the
    number of completions replayed.
    """
    n = 0
    table_sql = _table_sql(table)
    for key, payload in conn.execute(
        f"SELECT idempotency_key, payload FROM {table_sql} ORDER BY seq"
    ):
        apply(key, json.loads(payload))
        n += 1
    return n
