"""Temporal-backed durable execution for BENE agent workflows.

This package contains the building blocks for running BENE agents as Temporal
Workflows so they survive worker restarts and scale horizontally.

Layout:
    activities.py   — side-effecting Activities (LLM calls, VFS writes,
                      tool execution, audit logging)
    workflow.py     — :class:`AgentWorkflow` (deterministic agent loop)
    worker.py       — Worker bootstrap (wires activities + workflows + storage)
    runtime.py      — Process-wide singletons (storage / blob store / providers)

Install dependencies with::

    pip install 'bene[temporal]'

Quickstart::

    bene temporal worker --address localhost:7233 --queue bene-main \\
        --postgres-dsn YOUR_DSN_HERE
    bene temporal run --address localhost:7233 --queue bene-main \\
        --name demo-agent --prompt "Say hello"
"""

from __future__ import annotations

__all__ = [
    "AgentWorkflow",
    "AgentInput",
    "build_worker",
    "TemporalRuntime",
]

import importlib.util as _importlib_util

# Gate behind temporalio dep ONLY. Errors inside our own modules must surface,
# not be swallowed by a catch-all ``except ImportError``.
if _importlib_util.find_spec("temporalio") is not None:
    from bene.temporal.runtime_impl import TemporalRuntime
    from bene.temporal.worker import build_worker
    from bene.temporal.workflow import AgentInput, AgentWorkflow
