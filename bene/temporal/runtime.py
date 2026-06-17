"""Process-wide singletons for BENE Temporal workers.

Activities cannot accept arbitrary objects as arguments — Temporal serializes
inputs across the wire. We therefore stash long-lived dependencies (storage
backend, blob store, provider registry) in module-level globals that the
worker bootstrap initializes before starting.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from bene.storage.protocol import BlobStore, Storage


_STORAGE: Storage | None = None
_BLOBS: BlobStore | None = None
_LLM_HANDLER: Callable[[str, str, str], Awaitable[dict]] | None = None
_TOOL_HANDLER: Callable[[str, dict], Awaitable[dict]] | None = None


def configure(
    storage: Storage,
    blobs: BlobStore,
    *,
    llm_handler: Callable[[str, str, str], Awaitable[dict]] | None = None,
    tool_handler: Callable[[str, dict], Awaitable[dict]] | None = None,
) -> None:
    """Install the dependencies the Temporal Activities need at runtime.

    ``llm_handler`` signature: ``async (model, prompt, agent_id) -> dict``.
    The default echo handler used by the MVP just turns the prompt back into a
    finish payload — replace with real provider wiring at deployment time.
    """
    global _STORAGE, _BLOBS, _LLM_HANDLER, _TOOL_HANDLER
    _STORAGE = storage
    _BLOBS = blobs
    _LLM_HANDLER = llm_handler or _default_llm
    _TOOL_HANDLER = tool_handler or _default_tool


def get_storage() -> Storage:
    if _STORAGE is None:
        raise RuntimeError(
            "bene.temporal.runtime not configured. "
            "Call configure(storage=..., blobs=...) before starting the worker."
        )
    return _STORAGE


def get_blobs() -> BlobStore:
    if _BLOBS is None:
        raise RuntimeError("bene.temporal.runtime not configured")
    return _BLOBS


def get_llm_handler() -> Callable[[str, str, str], Awaitable[dict]]:
    if _LLM_HANDLER is None:
        raise RuntimeError("bene.temporal.runtime not configured")
    return _LLM_HANDLER


def get_tool_handler() -> Callable[[str, dict], Awaitable[dict]]:
    if _TOOL_HANDLER is None:
        raise RuntimeError("bene.temporal.runtime not configured")
    return _TOOL_HANDLER


async def _default_llm(model: str, prompt: str, agent_id: str) -> dict:
    """Echo handler used in tests and the docker-compose smoke demo.

    Returns ``{"finish": True, "output": prompt}`` so the workflow loop
    terminates after a single step. Real deployments should pass a real LLM
    handler that returns ``{"tool_call": {...}}`` or ``{"finish": ..., "output": ...}``.
    """
    del model, agent_id
    return {"finish": True, "output": f"echo: {prompt}"}


async def _default_tool(tool: str, input_data: dict) -> dict:
    """Default tool handler — returns the input as the output."""
    return {"tool": tool, "output": input_data}
