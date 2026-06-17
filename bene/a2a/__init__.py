"""A2A (Agent2Agent) endpoint for BENE — the durable cross-agent comms channel.

bene speaks the standard Google **Agent2Agent** protocol via the official
``a2a-sdk`` (not a hand-roll), so any A2A-conformant agent can join. The endpoint
is *seated on bene's SQLite*: the A2A task lifecycle persists in a small
``a2a_tasks`` table and every coordination message is mirrored into the existing
``SharedLog`` (intent / vote / decide / mail) for durable, auditable read-back.

Optional dependency — install with ``pip install "bene[a2a]"``. Importing this
package requires ``a2a-sdk``; the rest of ``bene`` does not.
"""

from __future__ import annotations

try:
    import a2a  # noqa: F401
except ModuleNotFoundError as e:  # pragma: no cover - import guard
    raise ModuleNotFoundError(
        "bene.a2a requires the 'a2a' extra. Install it with: pip install \"bene[a2a]\""
    ) from e

from bene.a2a.card import build_bene_agent_card
from bene.a2a.executor import BeneAgentExecutor
from bene.a2a.server import build_app, serve
from bene.a2a.store import SharedLogTaskStore

__all__ = [
    "BeneAgentExecutor",
    "SharedLogTaskStore",
    "build_app",
    "build_bene_agent_card",
    "serve",
]
