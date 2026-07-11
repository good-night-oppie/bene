"""The bene A2A AgentExecutor — maps incoming A2A messages onto SharedLog.

A peer addresses bene over A2A; the message ``kind`` (from message metadata or a
leading DataPart) routes it to the matching SharedLog verb:

    intent   -> SharedLog.intent   (returns an intent_id peers vote on)
    proposal -> SharedLog.intent   (tagged kind=proposal)
    vote     -> SharedLog.vote      (needs data.intent_id + data.approve)
    decide   -> SharedLog.decide    (needs data.intent_id)
    mail / * -> SharedLog.mail       (the default; never crashes)

Every message lands in bene.db and is readable back via SharedLog — the durable
coordination ledger. The reply is a completed Task carrying the SharedLog id, so
the peer can cite the exact entry.
"""

from __future__ import annotations

import json
import sqlite3

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.utils import get_data_parts, get_message_text, new_agent_text_message, new_task

from bene.shared_log import SharedLog


class BeneAgentExecutor(AgentExecutor):
    """Routes A2A messages to SharedLog coordination verbs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _harness(self, kind: str, sender: str, text: str, data: dict) -> tuple[str, int]:
        """Engine ops over A2A. ``harness.validate`` runs the sandboxed AST+smoke
        gate (B1) synchronously; ``harness.propose`` points at MetaHarnessSearch."""
        from bene.metaharness.harness_store import HarnessEngine

        log = SharedLog(self._conn)
        if kind == "harness.validate":
            source = (data.get("source") if isinstance(data, dict) else None) or text or ""
            res = HarnessEngine().validate(source).to_dict()
            entry = log.mail(
                "bene",
                sender,
                f"harness.validate ok={res['ok']}",
                metadata={"via": "a2a", "kind": kind, "result": res},
            )
            return f"harness.validate: {json.dumps(res)}", entry.log_id
        note = HarnessEngine.propose_via_search_note()
        entry = log.mail("bene", sender, note, metadata={"via": "a2a", "kind": kind})
        return f"harness.propose: {note}", entry.log_id

    def _record(self, kind: str, sender: str, text: str, data: dict) -> tuple[str, int]:
        """Map (kind, payload) -> a SharedLog entry. Falls back to mail on any
        malformed typed payload so a peer can never crash the endpoint."""
        log = SharedLog(self._conn)
        try:
            if kind == "intent":
                return "intent", log.intent(sender, text or data.get("action", ""), {"via": "a2a"})
            if kind == "proposal":
                return "proposal", log.intent(
                    sender, text or "proposal", {"via": "a2a", "kind": "proposal", "data": data}
                )
            if kind == "vote":
                intent_id = int(data["intent_id"])
                entry = log.vote(sender, intent_id, bool(data.get("approve", True)), reason=text)
                return "vote", entry.log_id
            if kind in ("decide", "decision"):
                entry = log.decide(int(data["intent_id"]), sender)
                return "decision", entry.log_id
        except (KeyError, ValueError, TypeError):
            pass  # malformed typed payload -> durable mail fallback below
        recipient = data.get("recipient")
        if not isinstance(recipient, str) or not recipient.strip():
            recipient = "bene"
        else:
            recipient = recipient.strip()
        entry = log.mail(
            sender, recipient, text or json.dumps(data), metadata={"via": "a2a", "kind": kind}
        )
        return "mail", entry.log_id

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        msg = context.message
        text = (get_message_text(msg) if msg else "") or (context.get_user_input() or "")
        data_parts = get_data_parts(msg.parts) if (msg and msg.parts) else []
        data0 = data_parts[0] if data_parts else {}
        meta = (msg.metadata if (msg and msg.metadata) else {}) or {}
        sender = str(meta.get("agent") or meta.get("from") or data0.get("agent") or "a2a:peer")
        kind = str(meta.get("kind") or data0.get("kind") or "mail").lower()
        data = data0 if isinstance(data0, dict) else {}

        if kind.startswith("harness."):
            reply, log_id = self._harness(kind, sender, text, data)
        else:
            verb, log_id = self._record(kind, sender, text, data)
            reply = f"bene recorded [{verb}] from {sender} -> shared_log#{log_id}"

        task = context.current_task
        if task is None:
            task = new_task(msg)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.complete(message=new_agent_text_message(reply, task.context_id, task.id))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError(
            "bene A2A coordination tasks complete synchronously; cancel is a no-op"
        )
