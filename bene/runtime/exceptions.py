"""BENE runtime exception hierarchy.

Both LocalRuntime and TemporalRuntime raise from this hierarchy. TemporalRuntime
wraps backend-specific exceptions (WorkflowNotFoundError, WorkflowAlreadyStartedError,
WorkflowQueryRejectedError, ApplicationError) into the matching subtype, preserving
the original in ``__cause__``.

No imports from ``temporalio`` or ``bene/temporal/`` permitted.
"""

from __future__ import annotations


class BeneRuntimeError(RuntimeError):
    """Base for all BENE runtime exceptions."""


class ActorNotFoundError(BeneRuntimeError):
    """Actor lookup failed — workflow_id not tracked by this runtime."""


class ActorAlreadyRunningError(BeneRuntimeError):
    """``submit()`` called with a workflow_id that already has a live actor."""


class ActorCompletedError(BeneRuntimeError):
    """``await_signal()`` called on a completed actor with no queued signals.

    Without this, ``await_signal`` would block forever — the actor is done and
    no further signals will be delivered. Raised explicitly so consumers can
    treat it as terminal rather than a hang.
    """


class QueryNotReadyError(BeneRuntimeError):
    """Query result not available.

    On LocalRuntime: PERMANENT — caller forgot
    ``register_query_result(workflow_id, name, value)``. Retrying the query
    will not help; no event signals availability.

    On TemporalRuntime: TRANSIENT — workflow may not have replayed to the
    query handler registration yet. Retry-with-backoff is appropriate, bounded
    by a timeout.

    Do NOT write retry loops on ``QueryNotReadyError`` without a timeout —
    they deadlock on LocalRuntime.
    """


class SideEffectFailedError(BeneRuntimeError):
    """``execute_fn`` raised; side effect is in FAILED terminal state on
    LocalRuntime (or after RetryPolicy exhaustion on TemporalRuntime).

    Original exception in ``__cause__``.
    """
