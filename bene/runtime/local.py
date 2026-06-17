"""LocalRuntime — in-memory implementation of the Runtime protocol.

This is the test double consumers (including agent-trace) use for unit tests.
It must behave identically to TemporalRuntime for the Runtime protocol surface.

No imports from ``temporalio`` or ``bene/temporal/`` permitted.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bene.runtime.core import (
    BusinessIdempotencyKey,
    SideEffectKind,
    SideEffectLabel,
)
from bene.runtime.exceptions import (
    ActorAlreadyRunningError,
    ActorCompletedError,
    ActorNotFoundError,
    QueryNotReadyError,
    SideEffectFailedError,
)
from bene.runtime.handle import RunHandle, TypedQuery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Side-effect ledger
# ---------------------------------------------------------------------------


class _LedgerState(str, Enum):
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class _LedgerEntry:
    state: _LedgerState
    result: Any = None
    # BaseException widens to cover asyncio.CancelledError captured in
    # submit_side_effect's BaseException catch (HID-01); Exception alone
    # would lose cancellation context on the ledger entry.
    error: BaseException | None = None


# ---------------------------------------------------------------------------
# In-memory actor registry entry
# ---------------------------------------------------------------------------


@dataclass
class _ActorEntry:
    handle: RunHandle
    signals: list[tuple[str, Any]]
    query_results: dict[str, Any]
    task: asyncio.Task[Any] | None = None


# ---------------------------------------------------------------------------
# LocalRuntime
# ---------------------------------------------------------------------------


class LocalRuntime:
    """In-memory Runtime implementation for unit-testing and local development.

    State is intentionally NOT durable across restarts. Completed actors are
    NOT garbage-collected — _actors / _run_results / _run_events grow unbounded
    across submits; call clear() to reset (HID-03).

    ## Test-only methods (not on Runtime protocol)

    register_query_result(workflow_id, query_name, value):
        Pre-load a query result. Call before code under test calls query().
    ledger_state(business_key) -> str | None:
        Return current ledger state ("executing", "done", "failed") or None.
    actor_ids() -> list[str]:
        Return workflow_ids of all currently tracked actors.
    clear():
        Reset all runtime state in-place. Use in autouse teardown fixtures.
    """

    def __init__(self) -> None:
        self._actors: dict[str, _ActorEntry] = {}
        self._side_effect_ledger: dict[str, _LedgerEntry] = {}
        self._run_results: dict[str, Any] = {}
        self._run_events: dict[str, asyncio.Event] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._workflow_locks: dict[str, asyncio.Lock] = {}
        self._signal_queues: dict[tuple[str, str], asyncio.Queue[Any]] = {}

    # ------------------------------------------------------------------ #
    # submit / await_result
    # ------------------------------------------------------------------ #

    async def submit(self, spec: Any) -> RunHandle:
        """Start a spec in an asyncio task and return a handle immediately.

        The spec must have a ``run_id`` attribute (or one is generated from
        ``getattr(spec, "workflow_id", None)``).
        """
        run_id: str = (
            getattr(spec, "run_id", None)
            or getattr(spec, "workflow_id", None)
            or f"local-{id(spec)}"
        )
        workflow_id: str = getattr(spec, "workflow_id", run_id)
        if workflow_id in self._actors:
            raise ActorAlreadyRunningError(
                f"Actor already running for workflow_id={workflow_id!r}. "
                f"Use start_or_signal for idempotent admission."
            )
        handle = RunHandle(run_id=run_id, workflow_id=workflow_id)
        done_event = asyncio.Event()
        self._run_events[run_id] = done_event

        run_fn = getattr(spec, "run", None)
        if run_fn is not None:

            async def _wrap() -> None:
                try:
                    result = await run_fn()
                    self._run_results[run_id] = result
                except Exception as exc:
                    self._run_results[run_id] = exc
                finally:
                    done_event.set()

            task = asyncio.create_task(_wrap())
        else:
            self._run_results[run_id] = None
            done_event.set()
            task = None

        entry = _ActorEntry(
            handle=handle,
            signals=[],
            query_results={},
            task=task,
        )
        self._actors[workflow_id] = entry
        return handle

    async def await_result(self, handle: RunHandle) -> Any:
        """Wait for the run to complete and return its result."""
        event = self._run_events.get(handle.run_id)
        if event is not None:
            await event.wait()
        result = self._run_results.get(handle.run_id)
        if isinstance(result, Exception):
            raise result
        return result

    # ------------------------------------------------------------------ #
    # signal / query
    # ------------------------------------------------------------------ #

    async def signal(self, handle: RunHandle, signal_name: str, payload: Any = None) -> None:
        """Deliver a signal to an actor's pending-signals list."""
        entry = self._actors.get(handle.workflow_id)
        if entry is None:
            raise ActorNotFoundError(f"No actor for workflow_id={handle.workflow_id!r}")
        entry.signals.append((signal_name, payload))
        q = self._signal_queues.setdefault((handle.workflow_id, signal_name), asyncio.Queue())
        q.put_nowait(payload)

    async def await_signal(self, handle: RunHandle, signal_name: str) -> Any:
        """Block until a matching signal is delivered; return its payload.

        Pre-delivered signals are returned immediately (FIFO per signal_name).
        If the actor has completed AND the queue is empty, raise
        ActorCompletedError rather than blocking forever (INV-09f).

        No timeout in Phase-1. Wrap in asyncio.wait_for for SLA-bounded waits.
        """
        entry = self._actors.get(handle.workflow_id)
        if entry is None:
            raise ActorNotFoundError(f"No actor for workflow_id={handle.workflow_id!r}")
        q = self._signal_queues.setdefault((handle.workflow_id, signal_name), asyncio.Queue())
        done_event = self._run_events.get(handle.run_id)
        if done_event is not None and done_event.is_set() and q.empty():
            raise ActorCompletedError(
                f"Actor workflow_id={handle.workflow_id!r} has completed and no "
                f"{signal_name!r} signals are queued."
            )
        return await q.get()

    async def get_handle(self, workflow_id: str) -> RunHandle:
        """Return the handle for an existing actor; raise ActorNotFoundError if absent.

        Eager existence check on both backends. TemporalRuntime calls
        describe_workflow to validate; LocalRuntime checks _actors dict.
        """
        entry = self._actors.get(workflow_id)
        if entry is None:
            raise ActorNotFoundError(f"No actor tracked for workflow_id={workflow_id!r}")
        return entry.handle

    async def query(self, handle: RunHandle, query: TypedQuery[Any]) -> Any:
        """Return a value previously registered under the query name."""
        entry = self._actors.get(handle.workflow_id)
        if entry is None:
            raise ActorNotFoundError(f"No actor for workflow_id={handle.workflow_id!r}")
        if query.name not in entry.query_results:
            raise QueryNotReadyError(
                f"Query {query.name!r} not registered for workflow_id={handle.workflow_id!r}. "
                f"Call rt.register_query_result(workflow_id, {query.name!r}, value) "
                f"in your test setup."
            )
        return entry.query_results[query.name]

    def register_query_result(self, workflow_id: str, query_name: str, value: Any) -> None:
        """Helper for tests: pre-load a query result."""
        entry = self._actors.get(workflow_id)
        if entry is None:
            raise ActorNotFoundError(f"No actor registered for workflow_id={workflow_id!r}")
        entry.query_results[query_name] = value

    # ------------------------------------------------------------------ #
    # start_or_signal
    # ------------------------------------------------------------------ #

    async def start_or_signal(self, spec: Any, signal_name: str, payload: Any) -> RunHandle:
        """Atomically admit an entity actor and deliver the first signal.

        If an actor with the same workflow_id is already tracked, deliver the
        signal to it and return the existing handle. Otherwise, submit a new
        spec and then deliver the signal.
        """
        workflow_id: str = getattr(spec, "workflow_id", None) or str(id(spec))
        lock = self._workflow_locks.setdefault(workflow_id, asyncio.Lock())
        async with lock:
            existing = self._actors.get(workflow_id)
            if existing is not None:
                await self.signal(existing.handle, signal_name, payload)
                return existing.handle
            handle = await self.submit(spec)
            await self.signal(handle, signal_name, payload)
            return handle

    # ------------------------------------------------------------------ #
    # submit_side_effect
    # ------------------------------------------------------------------ #

    async def submit_side_effect(
        self,
        label: SideEffectLabel,
        business_key: tuple[str, ...],
        execute_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Atomically admit and execute a side effect with in-memory ledger.

        Implements the ledger state machine::

            (absent) → EXECUTING → DONE | FAILED

        The lock guarantees only one concurrent ``execute_fn`` per ``business_key``.
        A second call with the same ``business_key`` while ``DONE`` returns the
        cached result without calling ``execute_fn`` again.

        Retry budget is NOT declared on SideEffectLabel. On TemporalRuntime,
        retry semantics belong to the Temporal RetryPolicy registered at
        activity scheduling time. LocalRuntime fails permanently on first
        exception (FAILED is terminal). Do NOT assert ledger_state == "failed"
        in tests that expect to reflect production Temporal behavior.
        """
        if label.kind == SideEffectKind.EXTERNAL_WRITE and not label.cost_estimate.confirmed_free:
            if label.cost_estimate.dollars < 0 or label.cost_estimate.latency_ms < 0:
                raise ValueError(
                    f"CostEstimate fields must be non-negative. Got "
                    f"dollars={label.cost_estimate.dollars}, "
                    f"latency_ms={label.cost_estimate.latency_ms}. "
                    f"semantic_class={label.semantic_class!r}."
                )
            if label.cost_estimate.dollars == 0.0 and label.cost_estimate.latency_ms == 0:
                raise ValueError(
                    f"EXTERNAL_WRITE requires explicit cost_estimate. "
                    f"semantic_class={label.semantic_class!r} has dollars=0, "
                    f"latency_ms=0. If genuinely free, pass "
                    f"CostEstimate(confirmed_free=True)."
                )
        if label.kind == SideEffectKind.EXTERNAL_WRITE and label.reconciliation_strategy is None:
            import warnings

            warnings.warn(
                f"EXTERNAL_WRITE with reconciliation_strategy=None is unsafe on "
                f"TemporalRuntime (TOCTOU on activity retry). "
                f"semantic_class={label.semantic_class!r}. "
                f"Set ReconciliationStrategy.MANUAL if human remediation is your intent.",
                stacklevel=2,
            )

        bik = BusinessIdempotencyKey(parts=business_key)
        key = bik.serialize()

        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        async with self._locks[key]:
            entry = self._side_effect_ledger.get(key)
            if entry is not None and entry.state == _LedgerState.DONE:
                return entry.result
            if entry is not None and entry.state == _LedgerState.FAILED:
                raise entry.error  # type: ignore[misc]

            self._side_effect_ledger[key] = _LedgerEntry(state=_LedgerState.EXECUTING)
            try:
                result = await execute_fn()
            except BaseException as exc:
                # BaseException catches asyncio.CancelledError (BaseException
                # since 3.8). Without this, cancellation leaves ledger stuck at
                # EXECUTING with the lock released via async-with __aexit__ →
                # second caller re-enters and may double-execute. HID-01.
                #
                # INV-07 — consumer must never see backend-specific exception
                # envelope: wrap raw activity exceptions in SideEffectFailedError
                # (with the original preserved via __cause__) so LocalRuntime and
                # TemporalRuntime present a single typed exception surface.
                # CancelledError and already-wrapped SideEffectFailedError pass
                # through raw — cancellation is a control-flow signal, and a
                # pre-wrapped SEF means a nested submit_side_effect failed.
                if isinstance(exc, (asyncio.CancelledError, SideEffectFailedError)):
                    self._side_effect_ledger[key] = _LedgerEntry(
                        state=_LedgerState.FAILED, error=exc
                    )
                    raise
                wrapped = SideEffectFailedError(
                    f"side_effect execution failed: {type(exc).__name__}"
                )
                wrapped.__cause__ = exc
                self._side_effect_ledger[key] = _LedgerEntry(
                    state=_LedgerState.FAILED, error=wrapped
                )
                raise wrapped from exc
            self._side_effect_ledger[key] = _LedgerEntry(state=_LedgerState.DONE, result=result)
            return result

    def ledger_state(self, business_key: tuple[str, ...]) -> str | None:
        """Return the current ledger state string for a business key, or None."""
        bik = BusinessIdempotencyKey(parts=business_key)
        entry = self._side_effect_ledger.get(bik.serialize())
        return entry.state.value if entry is not None else None

    def actor_ids(self) -> list[str]:
        """Return workflow_ids of currently tracked actors. Test-only."""
        return list(self._actors.keys())

    def clear(self) -> None:
        """Reset all in-place state. Test-only.

        HID-03: LocalRuntime does not garbage-collect completed actors;
        _actors / _run_results / _run_events grow unbounded across submits.
        Call clear() in autouse teardown fixtures. In-flight asyncio tasks
        are NOT cancelled — they complete in the background with results
        discarded. Call clear() only after all expected await_result() calls
        have completed.
        """
        self._actors.clear()
        self._side_effect_ledger.clear()
        self._run_results.clear()
        self._run_events.clear()
        self._locks.clear()
        self._workflow_locks.clear()
        self._signal_queues.clear()
