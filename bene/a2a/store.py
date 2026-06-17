"""A2A TaskStore seated on bene's SQLite.

The a2a-sdk needs somewhere to persist the A2A task lifecycle. Rather than the
default in-memory store, we persist tasks in a small ``a2a_tasks`` table in the
SAME ``bene.db`` both teams already audit — so a task survives a server restart
and is readable with stdlib ``sqlite3`` (no client library). The coordination
*content* (intent/vote/decide/mail) is mirrored separately into ``SharedLog`` by
the executor; this store is the protocol-state half.
"""

from __future__ import annotations

import sqlite3

from a2a.server.tasks import TaskStore
from a2a.types import Task

_SCHEMA = """
CREATE TABLE IF NOT EXISTS a2a_tasks (
    task_id    TEXT PRIMARY KEY,
    context_id TEXT,
    state      TEXT,
    task_json  TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
)
"""


class SharedLogTaskStore(TaskStore):
    """Durable A2A TaskStore over a bene SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def _state(task: Task) -> str | None:
        status = getattr(task, "status", None)
        state = getattr(status, "state", None) if status else None
        return getattr(state, "value", None) or (str(state) if state is not None else None)

    async def save(self, task: Task, context=None) -> None:
        self._conn.execute(
            "INSERT INTO a2a_tasks (task_id, context_id, state, task_json, updated_at)"
            " VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%f','now'))"
            " ON CONFLICT(task_id) DO UPDATE SET context_id=excluded.context_id,"
            " state=excluded.state, task_json=excluded.task_json, updated_at=excluded.updated_at",
            (task.id, getattr(task, "context_id", None), self._state(task), task.model_dump_json()),
        )
        self._conn.commit()

    async def get(self, task_id: str, context=None) -> Task | None:
        row = self._conn.execute(
            "SELECT task_json FROM a2a_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return Task.model_validate_json(row[0])

    async def delete(self, task_id: str, context=None) -> None:
        self._conn.execute("DELETE FROM a2a_tasks WHERE task_id = ?", (task_id,))
        self._conn.commit()
