"""Assemble + serve the bene A2A endpoint (Starlette/JSON-RPC, a2a-sdk)."""

from __future__ import annotations

from typing import Any

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler

from bene.a2a.card import DEFAULT_URL, build_bene_agent_card
from bene.a2a.executor import BeneAgentExecutor
from bene.a2a.store import SharedLogTaskStore


def build_app(db_path: str, url: str = DEFAULT_URL, *, version: str | None = None) -> Any:
    """Build the Starlette ASGI app: bene Agent Card at /.well-known/agent-card.json
    + JSON-RPC message/send, seated on the bene.db at ``db_path``."""
    from bene import Bene

    conn = Bene(db_path).conn  # ensures the base schema (shared_log table) exists
    card = build_bene_agent_card(url, version=version)
    handler = DefaultRequestHandler(
        agent_executor=BeneAgentExecutor(conn),
        task_store=SharedLogTaskStore(conn),
    )
    return A2AStarletteApplication(agent_card=card, http_handler=handler).build()


def serve(
    db_path: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8710,
    url: str | None = None,
) -> None:
    """Stand up the endpoint with uvicorn (blocking)."""
    import uvicorn

    app = build_app(db_path, url or f"http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
