"""Runtime protocol and handle types for BENE.

No imports from ``temporalio`` or ``bene/temporal/`` permitted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Generic, Protocol, TypeVar

from bene.runtime.core import SideEffectLabel

T = TypeVar("T")


class TypedQuery(Generic[T]):
    """Typed query descriptor.

    Carry the return type as a generic parameter so that refactors of query
    names fail at type-check time rather than at runtime.
    """

    def __init__(self, name: str, result_type: type[T]) -> None:
        self.name = name
        self.result_type = result_type

    def __repr__(self) -> str:
        return f"TypedQuery({self.name!r}, {self.result_type.__name__})"


class RunHandle:
    """Opaque handle to a running agent. Backend-agnostic.

    TemporalRuntime wraps a Temporal workflow handle here.
    LocalRuntime wraps an asyncio task + in-memory state.
    """

    def __init__(self, run_id: str, workflow_id: str | None = None) -> None:
        self.run_id = run_id
        self.workflow_id = workflow_id or run_id

    def __repr__(self) -> str:
        return f"RunHandle(run_id={self.run_id!r}, workflow_id={self.workflow_id!r})"


class Runtime(Protocol):
    """Minimum viable runtime interface.

    Both LocalRuntime and TemporalRuntime must implement this surface.
    Temporal-specific names (``signal_with_start``, workflow handles) must
    NOT appear here — LocalRuntime must be a drop-in for unit tests.
    """

    async def submit(self, spec: Any) -> RunHandle:
        """Submit a new agent run and return a handle immediately."""
        ...

    async def await_result(self, handle: RunHandle) -> Any:
        """Block until the run completes and return its result."""
        ...

    async def signal(self, handle: RunHandle, signal_name: str, payload: Any = None) -> None:
        """Deliver a named signal to a running agent."""
        ...

    async def query(self, handle: RunHandle, query: TypedQuery[T]) -> T:
        """Retrieve typed state from a running or completed agent."""
        ...

    async def await_signal(self, handle: RunHandle, signal_name: str) -> Any:
        """Block until a signal with matching name is delivered to this actor.

        Pre-delivered signals are returned immediately in FIFO order. If the
        actor has already completed with no queued signals, raises
        ActorCompletedError.

        No timeout in Phase-1. Wrap in ``asyncio.wait_for`` for SLA-bounded
        waits. Phase-2 will add ``timeout: float | None`` once Temporal timer
        integration lands.
        """
        ...

    async def get_handle(self, workflow_id: str) -> RunHandle:
        """Return a handle for an existing actor; raise ActorNotFoundError if absent.

        Eager existence check on both backends. TemporalRuntime calls
        ``describe_workflow`` to validate; LocalRuntime checks its actor dict.
        """
        ...

    async def start_or_signal(self, spec: Any, signal_name: str, payload: Any) -> RunHandle:
        """Atomically admit an entity actor and deliver the first signal.

        If the actor (identified by ``spec.workflow_id``) is already running,
        deliver the signal to the existing handle. Otherwise submit a new run
        first, then deliver the signal.

        Wraps Temporal ``signal_with_start`` on the Temporal backend.
        """
        ...

    async def submit_side_effect(
        self,
        label: SideEffectLabel,
        business_key: tuple[str, ...],
        execute_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Atomically admit and execute a side effect with ledger protection.

        The runtime owns a ledger keyed by ``business_key`` (serialized via
        :meth:`BusinessIdempotencyKey.serialize`) with states::

            (absent) → executing → done | failed

        Only one worker holds ``executing`` for a given key at a time
        (fenced lease). On retry, the runtime uses
        ``label.reconciliation_strategy`` to decide whether the prior
        ``execute_fn`` already committed.

        This is the ONLY safe pattern for external writes. Splitting into
        check + record is a guaranteed TOCTOU race on activity retry.
        """
        ...
