"""TemporalRuntime — Temporal-backed implementation of the Runtime protocol.

Drop-in for LocalRuntime against the same ``Runtime`` Protocol surface. Same
source that targets ``bene.runtime.handle.Runtime`` can swap backends without
modification.

Side-effect ledger durability comes from Temporal's own activity history:
when ``submit_side_effect``'s ``execute_fn`` invokes ``workflow.execute_activity``
with a stable ``activity_id`` derived from ``business_key``, Temporal handles
retry, idempotency, and replay safety. This module enforces the cost +
reconciliation contract at the API surface and delegates ledger mechanics to
Temporal.

Contract for ``execute_fn`` callers on TemporalRuntime: from inside a workflow
context, wrap your activity invocation::

    bik = BusinessIdempotencyKey(parts=business_key)
    return await workflow.execute_activity(
        post_advisory_atomic,
        args,
        activity_id=bik.serialize(),
        retry_policy=RetryPolicy(...),
        schedule_to_close_timeout=...,
    )

Keeps dispatch grep-able (#4 codegen-friendly) and explicit about the
side-effect contract (#1).

Lives in ``bene/temporal/`` rather than ``bene/runtime/`` because the runtime
Protocol layer is enforced backend-agnostic (no ``temporalio`` imports).
Concrete backend bindings live in ``bene/temporal/`` (this file) and any
future ``bene/<backend>/runtime_impl.py``.
"""

from __future__ import annotations

import warnings
from collections.abc import Awaitable, Callable
from typing import Any

from temporalio.client import (
    Client,
    WorkflowFailureError,
    WorkflowQueryRejectedError,
)
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import (
    TerminatedError,
    WorkflowAlreadyStartedError,
)
from temporalio.service import RPCError, RPCStatusCode

from bene.runtime.core import (
    SideEffectKind,
    SideEffectLabel,
)
from bene.runtime.exceptions import (
    ActorAlreadyRunningError,
    ActorNotFoundError,
    BeneRuntimeError,
)
from bene.runtime.handle import RunHandle, Runtime, TypedQuery


def _validate_side_effect_label(label: SideEffectLabel) -> None:
    """Mirror LocalRuntime cost + reconciliation gating.

    Duplicated here to keep Phase-2 PR scope minimal. If a third Runtime
    backend lands, lift to ``bene.runtime.core``.
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
        warnings.warn(
            f"EXTERNAL_WRITE with reconciliation_strategy=None is unsafe on "
            f"TemporalRuntime (TOCTOU on activity retry). "
            f"semantic_class={label.semantic_class!r}. "
            f"Set ReconciliationStrategy.MANUAL if human remediation is your intent.",
            stacklevel=3,
        )


def _wrap_rpc_error(workflow_id: str, e: RPCError) -> Exception:
    """Translate a ``temporalio.service.RPCError`` to a bene Protocol type.

    NOT_FOUND maps to ``ActorNotFoundError`` so missing-actor lookups have a
    stable type. Every other RPC status (DEADLINE_EXCEEDED, UNAVAILABLE,
    PERMISSION_DENIED, etc.) wraps in ``BeneRuntimeError`` rather than
    leaking the ``temporalio.*`` exception class across the Protocol
    boundary — Phase-1 INV-07 and pillar #3 (Protocol-portable consumers
    must never see backend-specific exception types).
    """
    if e.status == RPCStatusCode.NOT_FOUND:
        return ActorNotFoundError(f"No workflow {workflow_id!r}")
    return BeneRuntimeError(
        f"Temporal RPC error [status={e.status.name}] for workflow {workflow_id!r}: {e}"
    )


class TemporalRuntime(Runtime):
    """Runtime Protocol implementation backed by a temporalio Client.

    Phase-2.0 surface: submit, await_result, signal, query, get_handle,
    start_or_signal, submit_side_effect. ``await_signal`` raises
    ``NotImplementedError`` (Phase-2.x — needs workflow-side state polling).
    ``register_query_result`` raises ``NotImplementedError`` because it is a
    LocalRuntime test-only helper that has no Temporal equivalent.

    All workflows submitted by this runtime share a single ``task_queue``.
    Per-spec task_queue dispatch is a Phase-2.x extension.

    Inherits from the ``Runtime`` Protocol so static type-checkers verify
    method-shape conformance at class definition rather than only at the
    first concrete-to-Protocol assignment downstream — pillar #3 of the
    design anchor (Protocol-portable, not concrete-bound).
    """

    def __init__(self, client: Client, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    # ------------------------------------------------------------------ #
    # submit / await_result
    # ------------------------------------------------------------------ #

    async def submit(self, spec: Any) -> RunHandle:
        workflow_class = getattr(spec, "workflow_class", None)
        if workflow_class is None:
            raise ValueError(
                "TemporalRuntime.submit requires spec.workflow_class. "
                "LocalRuntime-only specs (with .run callable) are not "
                "portable to Temporal — populate workflow_class + input."
            )
        workflow_id = getattr(spec, "workflow_id", None) or f"bene-{id(spec)}"
        try:
            handle = await self._client.start_workflow(
                workflow_class,
                getattr(spec, "input", None),
                id=workflow_id,
                task_queue=self._task_queue,
            )
        except WorkflowAlreadyStartedError as e:
            raise ActorAlreadyRunningError(
                f"Actor already running for workflow_id={workflow_id!r}. "
                f"Use start_or_signal for idempotent admission."
            ) from e
        except RPCError as e:
            raise _wrap_rpc_error(workflow_id, e) from e
        return RunHandle(run_id=handle.id, workflow_id=handle.id)

    async def await_result(self, handle: RunHandle) -> Any:
        wfh = self._client.get_workflow_handle(handle.workflow_id)
        try:
            return await wfh.result()
        except WorkflowFailureError as e:
            # INV-07: unwrap the underlying ApplicationError so consumers do
            # not have to know about the WorkflowFailureError envelope. The
            # `cause` is the user-facing exception raised inside the workflow.
            raise e.cause from e
        except RPCError as e:
            raise _wrap_rpc_error(handle.workflow_id, e) from e

    # ------------------------------------------------------------------ #
    # signal / query
    # ------------------------------------------------------------------ #

    async def signal(self, handle: RunHandle, signal_name: str, payload: Any = None) -> None:
        wfh = self._client.get_workflow_handle(handle.workflow_id)
        try:
            await wfh.signal(signal_name, payload)
        except TerminatedError as e:
            # Workflow was terminated before the signal landed; the actor no
            # longer exists from the consumer's perspective.
            raise ActorNotFoundError(
                f"Workflow {handle.workflow_id!r} was terminated; cannot deliver "
                f"signal {signal_name!r}."
            ) from e
        except RPCError as e:
            raise _wrap_rpc_error(handle.workflow_id, e) from e

    async def query(self, handle: RunHandle, query: TypedQuery[Any]) -> Any:
        wfh = self._client.get_workflow_handle(handle.workflow_id)
        try:
            return await wfh.query(query.name)
        except WorkflowQueryRejectedError as e:
            # Query rejection: workflow is in a state (closed, terminated)
            # that does not accept queries. Surface as ActorNotFoundError so
            # consumers handle "no live actor" with one stable type.
            raise ActorNotFoundError(
                f"Query {query.name!r} rejected for {handle.workflow_id!r} "
                f"(workflow not in queryable state): {e}"
            ) from e
        except RPCError as e:
            raise _wrap_rpc_error(handle.workflow_id, e) from e

    async def await_signal(self, handle: RunHandle, signal_name: str) -> Any:
        raise NotImplementedError(
            "await_signal on TemporalRuntime is Phase-2.x. The pattern requires "
            "workflow-side signal-queue state plus polling via query. Use a "
            "workflow-internal signal handler instead until then."
        )

    async def get_handle(self, workflow_id: str) -> RunHandle:
        wfh = self._client.get_workflow_handle(workflow_id)
        try:
            await wfh.describe()
        except RPCError as e:
            raise _wrap_rpc_error(workflow_id, e) from e
        return RunHandle(run_id=workflow_id, workflow_id=workflow_id)

    # ------------------------------------------------------------------ #
    # start_or_signal
    # ------------------------------------------------------------------ #

    async def start_or_signal(self, spec: Any, signal_name: str, payload: Any) -> RunHandle:
        workflow_class = getattr(spec, "workflow_class", None)
        if workflow_class is None:
            raise ValueError("TemporalRuntime.start_or_signal requires spec.workflow_class.")
        workflow_id = getattr(spec, "workflow_id", None) or f"bene-{id(spec)}"
        # Signal-with-start: if no execution exists (or the prior one failed
        # under ALLOW_DUPLICATE_FAILED_ONLY) Temporal starts a fresh workflow
        # and delivers the signal in a single RPC. If a RUNNING execution is
        # already present Temporal raises WorkflowAlreadyStartedError; we
        # catch that and signal the existing handle so the LocalRuntime
        # contract — "ensure running, deliver signal" — is preserved on the
        # Temporal backend. A previously-completed workflow under this policy
        # also raises WorkflowAlreadyStartedError; signaling a closed run
        # raises through the catch path (consumer gets a meaningful error).
        try:
            handle = await self._client.start_workflow(
                workflow_class,
                getattr(spec, "input", None),
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                start_signal=signal_name,
                start_signal_args=[payload] if payload is not None else [],
            )
        except WorkflowAlreadyStartedError:
            wfh = self._client.get_workflow_handle(workflow_id)
            try:
                await wfh.signal(signal_name, payload)
            except TerminatedError as te:
                raise ActorNotFoundError(
                    f"Workflow {workflow_id!r} was terminated; cannot deliver "
                    f"signal {signal_name!r}."
                ) from te
            except RPCError as re:
                raise _wrap_rpc_error(workflow_id, re) from re
            return RunHandle(run_id=workflow_id, workflow_id=workflow_id)
        except RPCError as e:
            raise _wrap_rpc_error(workflow_id, e) from e
        return RunHandle(run_id=handle.id, workflow_id=handle.id)

    # ------------------------------------------------------------------ #
    # submit_side_effect
    # ------------------------------------------------------------------ #

    async def submit_side_effect(
        self,
        label: SideEffectLabel,
        business_key: tuple[str, ...],
        execute_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Execute a side effect with API-surface contract enforcement.

        Cost validation and reconciliation gating mirror LocalRuntime. Ledger
        mechanics — retry, idempotency, replay — are delegated to Temporal:
        ``execute_fn`` is expected to internally invoke
        ``workflow.execute_activity(...)`` with ``activity_id`` derived from
        ``BusinessIdempotencyKey(business_key).serialize()``.

        From a workflow context, this is the canonical pattern. From outside
        workflow context, callers must spawn a one-shot workflow themselves;
        this runtime does not auto-lift arbitrary callables to activities
        (#1 explicit, #4 codegen-friendly — caller writes the lowering).

        Note on contract divergence from LocalRuntime:
        - LocalRuntime treats the first ``execute_fn`` raise as terminal-FAILED;
          subsequent calls with the same ``business_key`` see the FAILED entry
          and short-circuit.
        - TemporalRuntime delegates retry to Temporal's ``RetryPolicy`` on the
          activity invocation inside ``execute_fn``. Set
          ``RetryPolicy(maximum_attempts=1)`` on the inner activity to match
          LocalRuntime's "first-raise-wins" semantics.
        - The ``business_key`` argument is currently NOT enforced at the runtime
          boundary on this backend; the caller must thread it into
          ``activity_id``. A signature change that pushes the serialized key
          into ``execute_fn`` (so the runtime can enforce derivation) is filed
          as a Phase-2.x follow-up.
        """
        _validate_side_effect_label(label)
        return await execute_fn()

    # ------------------------------------------------------------------ #
    # register_query_result — LocalRuntime test-only; not on Temporal
    # ------------------------------------------------------------------ #

    def register_query_result(self, workflow_id: str, query_name: str, value: Any) -> None:
        """LocalRuntime test-only helper; not implemented on Temporal.

        Raises ``NotImplementedError`` with an actionable message rather than
        leaking ``AttributeError`` when consumers reach for the LocalRuntime
        helper through a ``Runtime``-typed fixture.
        """
        raise NotImplementedError(
            "register_query_result is a LocalRuntime test-only helper. "
            "TemporalRuntime query results come from live workflow query "
            "handlers; in tests use a WorkflowEnvironment with a real workflow "
            "class that defines @workflow.query(...) handlers instead."
        )
