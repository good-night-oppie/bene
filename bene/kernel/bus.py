"""Kernel event bus — synchronous at-least-once dispatch with handler isolation.

Contract: docs/design/KERNEL-SPEC.md §2.2. Events optionally mirror into the
legacy append-only journal (bene/events.py) when an agent_id is supplied, so
the legacy UI/logs see kernel activity (D10: adapters, not rewrites).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import ulid

from bene.events import EventJournal

logger = logging.getLogger(__name__)

WILDCARD = "*"


class EventBus:
    def __init__(self, journal: EventJournal | None = None) -> None:
        self._journal = journal
        # event_type -> {sub_id: handler}
        self._subs: dict[str, dict[str, Callable[[dict[str, Any]], None]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> str:
        sub_id = str(ulid.new())
        self._subs.setdefault(event_type, {})[sub_id] = handler
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        for handlers in self._subs.values():
            handlers.pop(sub_id, None)

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> None:
        """Dispatch to all handlers for ``event_type`` and ``*``.

        A failing handler is isolated (logged); remaining handlers still run.
        Mirrors to the legacy journal when attached and an agent_id is given
        (the legacy events table requires an agent FK).
        """
        event = {"event_type": event_type, "agent_id": agent_id, **payload}
        for et in (event_type, WILDCARD):
            for sub_id, handler in list(self._subs.get(et, {}).items()):
                try:
                    handler(event)
                except Exception:  # noqa: BLE001 — isolation is the contract
                    logger.exception("event handler %s failed for %s", sub_id, event_type)
        if self._journal is not None and agent_id is not None:
            try:
                self._journal.log(agent_id, f"kernel.{event_type}", payload)
            except Exception:  # noqa: BLE001
                logger.exception("journal mirror failed for %s", event_type)
