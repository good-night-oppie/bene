"""Capability registry — the kernel's syscall table.

Every capability carries a required autonomy level (L0..L4); dispatch is the
single enforcement point (D4). In phase 4 the autonomy check is a pluggable
callable (default: allow) — bene/kernel/harness/autonomy.py supplies the real
policy in phase 8. Denials emit a ``capability.denied`` bus event so the trust
ledger (phase 5) can record them.
Contract: docs/design/KERNEL-SPEC.md §2.3.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bene.kernel.bus import EventBus


class AutonomyDenied(PermissionError):
    """Raised when an agent's autonomy level is below the capability's."""


class UnknownCapability(KeyError):
    """Raised on lookup/dispatch of an unregistered capability."""


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    autonomy_level: int
    handler_ref: str | None
    metadata: dict[str, Any]


class CapabilityRegistry:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        bus: EventBus | None = None,
        autonomy_check: Callable[[str, "Capability"], bool] | None = None,
    ) -> None:
        self.conn = conn
        self.bus = bus
        # default policy (phase 4): allow — replaced by AutonomyPolicy.check in phase 8
        self._autonomy_check = autonomy_check or (lambda _agent, _cap: True)
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        name: str,
        *,
        autonomy_level: int,
        description: str,
        handler: Callable[..., Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not 0 <= autonomy_level <= 4:
            raise ValueError("autonomy_level must be 0..4")
        handler_ref = (
            f"{handler.__module__}.{getattr(handler, '__qualname__', repr(handler))}"
            if handler is not None
            else None
        )
        self.conn.execute(
            "INSERT INTO capabilities (name, description, autonomy_level, handler_ref, metadata)"
            " VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET description=excluded.description,"
            " autonomy_level=excluded.autonomy_level, handler_ref=excluded.handler_ref,"
            " metadata=excluded.metadata",
            (name, description, autonomy_level, handler_ref, json.dumps(metadata or {})),
        )
        self.conn.commit()
        if handler is not None:
            self._handlers[name] = handler

    def lookup(self, name: str) -> Capability:
        row = self.conn.execute(
            "SELECT name, description, autonomy_level, handler_ref, metadata"
            " FROM capabilities WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            raise UnknownCapability(name)
        return Capability(row[0], row[1], row[2], row[3], json.loads(row[4]))

    def list(self, *, max_level: int | None = None) -> list[Capability]:
        sql = "SELECT name, description, autonomy_level, handler_ref, metadata FROM capabilities"
        params: list[Any] = []
        if max_level is not None:
            sql += " WHERE autonomy_level <= ?"
            params.append(max_level)
        sql += " ORDER BY name"
        return [
            Capability(r[0], r[1], r[2], r[3], json.loads(r[4]))
            for r in self.conn.execute(sql, params).fetchall()
        ]

    def set_autonomy_check(self, check: Callable[[str, Capability], bool]) -> None:
        self._autonomy_check = check

    def dispatch(self, name: str, agent_id: str, /, *args: Any, **kwargs: Any) -> Any:
        """The enforcement point: autonomy check → handler. Denial raises
        AutonomyDenied and emits a ``capability.denied`` bus event."""
        cap = self.lookup(name)
        if not self._autonomy_check(agent_id, cap):
            if self.bus is not None:
                self.bus.publish(
                    "capability.denied",
                    {"capability": name, "required_level": cap.autonomy_level},
                    agent_id=agent_id,
                )
            raise AutonomyDenied(
                f"agent {agent_id} denied capability {name!r} (requires L{cap.autonomy_level})"
            )
        handler = self._handlers.get(name)
        if handler is None:
            raise UnknownCapability(f"{name} registered without an in-process handler")
        return handler(*args, **kwargs)
