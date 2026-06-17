"""Pass-3 consumer invariant test suite for bene/runtime (feat/runtime-core-phase1).

These 14 tests lock the contract for the 7 invariants the consumer
(agent-trace) owns per the Pass-2 ownership split:

    INV-01 — Ledger state machine (3 tests + HID-01 cancellation)
    INV-02 — start_or_signal atomicity (1 test)
    INV-03 — BusinessIdempotencyKey hash determinism (1 test)
    INV-07 — Exception type contract per protocol method (2 tests)
    INV-08 — Actor lifecycle on duplicate workflow_id (1 test)
    INV-09 — await_signal blocking semantics (4 tests)
    INV-10 — get_handle eager existence check (1 test)
    HID-03 — Actor accumulation observable (1 test)

Each test currently FAILS without the Pass-3 designer patches and PASSES
once they land. Tests are structured so a future TemporalRuntime fixture
can parametrize them without rewrite (see Deliverable 2 in the Pass-3
consumer reply).

Conventions:
    - Real LocalRuntime, no mocks.
    - asyncio.run() inside synchronous test fns (NOT pytest-asyncio).
      Rationale: consumer-side repos (e.g. triage-rag services/temporal_worker)
      do not install pytest-asyncio; the test must be runnable from any
      consumer that imports bene.

Run: uv run python -m pytest tests/test_runtime_invariants.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from bene.runtime.core import (
    BusinessIdempotencyKey,
    CostEstimate,
    SideEffectKind,
    SideEffectLabel,
)
from bene.runtime.exceptions import (
    ActorAlreadyRunningError,
    ActorCompletedError,
    ActorNotFoundError,
    QueryNotReadyError,
    BeneRuntimeError,
)
from bene.runtime.handle import RunHandle, TypedQuery
from bene.runtime.local import LocalRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SimpleSpec:
    """Minimal spec with run_id == workflow_id for LocalRuntime tests.

    No `run` method → spec completes synchronously inside submit() with
    result=None. Sufficient for actor-tracking tests.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.workflow_id = run_id


class _SlowSpec:
    """Spec that blocks on an event before completing.

    Used by INV-09 tests that need the actor to remain RUNNING while
    await_signal blocks. Completion is gated on `done_event.set()`.
    """

    def __init__(self, run_id: str, done_event: asyncio.Event) -> None:
        self.run_id = run_id
        self.workflow_id = run_id
        self._done = done_event

    async def run(self) -> None:
        await self._done.wait()


def _label(
    kind: SideEffectKind = SideEffectKind.EXTERNAL_WRITE,
    cost: CostEstimate | None = None,
) -> SideEffectLabel:
    """Default label that satisfies the Pass-3 cost guard.

    EXTERNAL_WRITE with non-zero latency_ms passes INV-04 guard (post-patch).
    Tests that target INV-04 build their own labels.
    """
    return SideEffectLabel(
        kind=kind,
        semantic_class="test_effect",
        rate_limit_class="test:default",
        cost_estimate=cost or CostEstimate(latency_ms=10, dollars=0.0),
    )


# ===========================================================================
# INV-01 — Ledger state machine + HID-01 cancellation
# ===========================================================================


def test_inv01_cancellation_marks_failed_not_executing() -> None:
    """INV-01 + HID-01: ledger reaches FAILED on asyncio.CancelledError, never stuck EXECUTING.

    Failure mode if invariant slips: bare `except Exception` does NOT catch
        CancelledError (BaseException since 3.8). Ledger stuck at EXECUTING;
        async-with releases the lock; second caller re-enters and double-writes.
    Catches: Patch 1.1 (try/except BaseException + try/except/else restructure).
    Temporal-readiness: TEMPORAL-READY — Temporal activity cancellation also
        surfaces as CancelledError; RetryPolicy decides resumption. Ledger
        introspection differs (event history vs in-memory dict); the assertion
        is "state is not EXECUTING after cancellation," which holds on both.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        key = ("inv01", "cancel-1")
        started = asyncio.Event()
        release = asyncio.Event()
        invocations = 0

        async def execute_fn() -> str:
            nonlocal invocations
            invocations += 1
            started.set()
            await release.wait()
            return "ok"

        async def caller() -> Any:
            return await rt.submit_side_effect(_label(), key, execute_fn)

        task = asyncio.create_task(caller())
        await started.wait()
        task.cancel()

        with pytest.raises((asyncio.CancelledError, BaseException)):
            await task

        # Invariant: ledger MUST NOT be stuck in EXECUTING.
        # Pass-3 designer choice: cancellation lands the ledger in FAILED
        # (CancelledError stored as the terminal error). The post-condition
        # "state != executing" survives any reasonable terminal choice.
        state = rt.ledger_state(key)
        assert state != "executing", (
            f"INV-01/HID-01 violated: ledger stuck at {state!r} after cancellation. "
            f"Without BaseException catch, the ledger stays at EXECUTING and a "
            f"second caller re-enters."
        )

        # Cancellation must NOT have caused a re-execution by some background
        # task; release stays unset.
        assert invocations == 1, f"execute_fn called {invocations} times; expected 1."

    asyncio.run(_run())


def test_inv01_done_reentry_returns_cached_result() -> None:
    """INV-01: second submit_side_effect with same key after DONE returns cached result.

    Failure mode if invariant slips: cache is bypassed; execute_fn called twice.
        On EXTERNAL_WRITE this is double-write.
    Catches: existing INV-01 cache-on-DONE path; this test guards against
        regressions in Patch 1.1's try/except/else restructure.
    Temporal-readiness: TEMPORAL-READY — Temporal activity_id dedup gives the
        same observable behavior (second activity execution is short-circuited
        when the first completed inside the workflow).
    """

    async def _run() -> None:
        rt = LocalRuntime()
        key = ("inv01", "done-reentry")
        execute_fn = AsyncMock(return_value={"id": "abc"})

        r1 = await rt.submit_side_effect(_label(), key, execute_fn)
        r2 = await rt.submit_side_effect(_label(), key, execute_fn)

        assert r1 == r2 == {"id": "abc"}
        execute_fn.assert_awaited_once()
        assert rt.ledger_state(key) == "done"

    asyncio.run(_run())


def test_inv01_failed_reentry_reraises() -> None:
    """INV-01: FAILED is terminal on Local; second call re-raises stored error without retry.

    Failure mode if invariant slips: failed call gets re-tried; execute_fn
        called twice; second raises a fresh exception (different identity).
    Catches: Patch 1.1 (FAILED state path). Pre-patch code already re-raises
        but commits FAILED inside `try`; restructured form preserves behavior
        and adds CancelledError coverage.

    INV-07: raw activity exceptions are wrapped in ``SideEffectFailedError``
        with the original preserved via ``__cause__`` — consumers see one
        typed exception envelope across LocalRuntime and TemporalRuntime
        rather than a backend-specific raw type.

    Temporal-readiness: LOCAL-ONLY — Temporal RetryPolicy means FAILED is not
        terminal until retries exhaust; this test explicitly asserts Local
        semantics. Phase-2 must mark this test `@pytest.mark.local_only` or
        adapt the assertion to "FAILED-after-retry-exhaustion is terminal."
    """

    async def _run() -> None:
        from bene.runtime.exceptions import SideEffectFailedError

        rt = LocalRuntime()
        key = ("inv01", "failed-reentry")

        class _Boom(RuntimeError):
            pass

        original_exc = _Boom("first call boom")
        invocations = 0

        async def execute_fn() -> str:
            nonlocal invocations
            invocations += 1
            raise original_exc

        with pytest.raises(SideEffectFailedError) as first_call:
            await rt.submit_side_effect(_label(), key, execute_fn)

        # __cause__ preserves the original raw exception identity for triage
        # / observability. Consumers that need the underlying type read it
        # off ``__cause__``; the catch surface is a single typed exception.
        assert first_call.value.__cause__ is original_exc

        # Second call: must re-raise the same wrapped SEF, not a fresh
        # exception, and must NOT call execute_fn again.
        with pytest.raises(SideEffectFailedError) as second_call:
            await rt.submit_side_effect(_label(), key, execute_fn)

        assert second_call.value is first_call.value, (
            "FAILED ledger entry must store the wrapped SideEffectFailedError; "
            "re-raise must use the same instance (preserves traceback context "
            "+ identity for replay determinism)."
        )
        assert second_call.value.__cause__ is original_exc
        assert invocations == 1
        assert rt.ledger_state(key) == "failed"

    asyncio.run(_run())


# ===========================================================================
# INV-02 — start_or_signal atomicity
# ===========================================================================


def test_inv02_concurrent_start_or_signal_atomic() -> None:
    """INV-02: 10 concurrent start_or_signal calls with same workflow_id → 1 actor, 10 signals.

    Failure mode if invariant slips: pre-patch start_or_signal has an `await
        self.signal(...)` between the dict lookup and the dict mutation. Two
        callers can both observe `existing is None`, both call submit() with
        the same workflow_id, the second's submit() overwrites the first's
        actor entry (along with its signals list). Net result: < 10 signals
        delivered, possibly only 1.
    Catches: Patch 1.2 (workflow_lock per workflow_id around the
        check-and-act block).
    Temporal-readiness: TEMPORAL-READY — Temporal SignalWithStart RPC is
        server-atomic. Same observable behavior; LocalRuntime's lock
        approximates Temporal's server-side atomicity at the asyncio level.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        spec = _SimpleSpec("inv02-concurrent")
        N = 10

        async def caller(i: int) -> RunHandle:
            return await rt.start_or_signal(spec, signal_name="event", payload={"i": i})

        handles = await asyncio.gather(*(caller(i) for i in range(N)))

        # Exactly one actor exists.
        actors_with_id = [wid for wid in rt._actors if wid == "inv02-concurrent"]
        assert len(actors_with_id) == 1
        # All callers got the same handle (same run_id).
        run_ids = {h.run_id for h in handles}
        assert len(run_ids) == 1

        # All 10 signals delivered.
        entry = rt._actors["inv02-concurrent"]
        signal_payloads = [p for (_name, p) in entry.signals]
        delivered_i = sorted(p["i"] for p in signal_payloads)
        assert delivered_i == list(range(N)), (
            f"INV-02 violated: expected {N} signals, got {len(signal_payloads)} "
            f"with i values {delivered_i}. Race window between the actor lookup "
            f"and the submit() call dropped signals."
        )

    asyncio.run(_run())


# ===========================================================================
# INV-03 — BusinessIdempotencyKey hash determinism + collision resistance
# ===========================================================================


def test_inv03_business_idempotency_key_collision_resistance() -> None:
    """INV-03: tuples differing only by colon placement produce different keys.

    Failure mode if invariant slips: caller-side `:`.join(parts) instead of
        runtime-owned null-byte serialization → ("a:b", "c") and ("a", "b:c")
        hash to the same key. On EXTERNAL_WRITE, this is a cross-tenant
        idempotency collision (one actor's write reuses another's ledger entry).
    Catches: Existing INV-03 holds (null-byte separator); Patch 1.10 adds an
        empty-parts guard. This test guards against regressions.
    Temporal-readiness: TEMPORAL-READY — hash computed client-side; same on
        both backends. Activity_id derived from the same serialization.
    """

    async def _run() -> None:
        k1 = BusinessIdempotencyKey(parts=("a:b", "c")).serialize()
        k2 = BusinessIdempotencyKey(parts=("a", "b:c")).serialize()
        assert k1 != k2, (
            f"INV-03 violated: ('a:b', 'c') and ('a', 'b:c') hash to same "
            f"key {k1!r}. Caller-supplied separator collides; runtime must "
            f"use a separator that cannot appear in the parts."
        )

        # Boundary: empty-parts must raise (Patch 1.10).
        with pytest.raises(ValueError, match="non-empty"):
            BusinessIdempotencyKey(parts=()).serialize()

        # Determinism: same input → same hash.
        k3 = BusinessIdempotencyKey(parts=("a:b", "c")).serialize()
        assert k1 == k3
        assert len(k1) == 32

    asyncio.run(_run())


# ===========================================================================
# INV-07 — Typed exception hierarchy
# ===========================================================================


def test_inv07_signal_dead_workflow_raises_typed_error() -> None:
    """INV-07: signal() on unknown workflow_id raises ActorNotFoundError, not KeyError.

    Failure mode if invariant slips: consumer catches KeyError to handle "dead
        workflow" but their `dict[run_id]` access elsewhere also raises KeyError;
        wrong code path triggered. TemporalRuntime would raise
        WorkflowNotFoundError; consumer's catch site diverges across backends.
    Catches: Patch 1.5 (typed exception hierarchy + raise-site replacements).
    Temporal-readiness: TEMPORAL-READY — TemporalRuntime's contract requires
        wrapping WorkflowNotFoundError → ActorNotFoundError, preserving the
        original in __cause__. Same exception class on both backends.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        ghost = RunHandle(run_id="never-submitted", workflow_id="never-submitted")

        with pytest.raises(ActorNotFoundError) as exc_info:
            await rt.signal(ghost, "any_signal", payload=None)
        assert isinstance(exc_info.value, BeneRuntimeError)
        # Bare KeyError must NOT match — typed hierarchy is the contract.
        assert not isinstance(exc_info.value, KeyError)

        # Same for query() on missing actor.
        with pytest.raises(ActorNotFoundError):
            await rt.query(ghost, TypedQuery("anything", str))

        # Same for register_query_result test helper.
        with pytest.raises(ActorNotFoundError):
            rt.register_query_result("never-submitted", "q", "v")

    asyncio.run(_run())


def test_inv07_query_not_registered_raises_typed_error() -> None:
    """INV-07: query() on registered actor without registered query raises QueryNotReadyError.

    Failure mode if invariant slips: bare KeyError leaks. Consumer who writes
        retry-on-KeyError loop deadlocks on Local (HID-02): query result is
        registered synchronously; no event will fire to make it appear later.
        QueryNotReadyError docstring carries the LOCAL-PERMANENT vs
        TEMPORAL-TRANSIENT distinction explicitly.
    Catches: Patch 1.5 (raise QueryNotReadyError + register_query_result hint
        in error message — friction-1 fold-in).
    Temporal-readiness: TEMPORAL-READY (class) but DIVERGENT-SEMANTICS:
        On Temporal, the query may succeed later as the workflow replays.
        Consumers must wrap retries in `asyncio.wait_for(..., timeout=N)` to
        avoid Local deadlock. Phase-2 contract documents this in the docstring.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        spec = _SimpleSpec("inv07-query")
        handle = await rt.submit(spec)
        # Note: NOT calling rt.register_query_result.

        with pytest.raises(QueryNotReadyError) as exc_info:
            await rt.query(handle, TypedQuery("never_registered", str))

        # The error message MUST hint at register_query_result so the consumer
        # is led to the test-only setup helper rather than a retry loop.
        assert "register_query_result" in str(exc_info.value), (
            "QueryNotReadyError message must include register_query_result hint "
            "(folded-in friction-1 fix)."
        )
        assert isinstance(exc_info.value, BeneRuntimeError)

    asyncio.run(_run())


# ===========================================================================
# INV-08 — Duplicate workflow_id submit raises
# ===========================================================================


def test_inv08_duplicate_workflow_id_raises() -> None:
    """INV-08: submit() called twice with same workflow_id raises ActorAlreadyRunningError.

    Failure mode if invariant slips: silent second-write to _actors clobbers
        the first actor's signals + task references. Existing actor is
        effectively decapitated from its task object (still running) but no
        longer reachable via the runtime; second caller's future signals go to
        a fresh _ActorEntry. Equivalent to a memory leak + a silent identity
        swap.
    Catches: Patch 1.6 (raise before any _actors mutation).
    Temporal-readiness: TEMPORAL-READY — Temporal's id_reuse_policy=
        REJECT_DUPLICATE on start_workflow raises WorkflowAlreadyStartedError;
        TemporalRuntime wraps it as ActorAlreadyRunningError per the Phase-2
        contract.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        spec = _SimpleSpec("inv08-dup")
        handle1 = await rt.submit(spec)

        with pytest.raises(ActorAlreadyRunningError):
            await rt.submit(spec)

        # Original actor unaffected.
        assert rt._actors["inv08-dup"].handle.run_id == handle1.run_id

        # start_or_signal must NOT raise — its semantics handle the existing case.
        h2 = await rt.start_or_signal(spec, "event", {"x": 1})
        assert h2.run_id == handle1.run_id
        assert rt._actors["inv08-dup"].signals[-1] == ("event", {"x": 1})

    asyncio.run(_run())


# ===========================================================================
# INV-09 — await_signal blocking semantics
# ===========================================================================


def test_inv09_await_signal_blocks_until_delivered() -> None:
    """INV-09a: await_signal blocks until a matching signal arrives.

    Failure mode if invariant slips: missing primitive forces consumer to poll
        rt._actors[wid].signals or busy-loop. await_signal is the documented
        suspension primitive used by post_advisory_composer for the human
        approval gate.
    Catches: Patch 1.7 (await_signal method + signal queue).
    Temporal-readiness: TEMPORAL-READY — wraps Temporal's wait_condition +
        signal handler queue inside the workflow function. FIFO ordering
        preserved on both backends.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        done_event = asyncio.Event()
        spec = _SlowSpec("inv09a", done_event)
        handle = await rt.submit(spec)

        async def signaler() -> None:
            await asyncio.sleep(0.05)  # let awaiter park
            await rt.signal(handle, "approve", {"ok": True})

        async def awaiter() -> Any:
            return await rt.await_signal(handle, "approve")

        signaler_task = asyncio.create_task(signaler())
        try:
            payload = await asyncio.wait_for(awaiter(), timeout=2.0)
        finally:
            done_event.set()
            await signaler_task

        assert payload == {"ok": True}

    asyncio.run(_run())


def test_inv09_signal_before_await_delivered() -> None:
    """INV-09b: signal delivered before await_signal returns immediately with payload.

    Failure mode if invariant slips: pre-delivered signal is lost. Consumer
        must always order signal-after-await, which is impossible across
        process boundaries (TemporalRuntime SignalWithStart). Pre-buffering is
        the only sane semantics.
    Catches: Patch 1.7 (signal pushes to asyncio.Queue; await_signal reads
        from queue; pre-existing items are returned without blocking).
    Temporal-readiness: TEMPORAL-READY — Temporal signal channel buffers
        signals on the workflow side until the workflow code reads them.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        done_event = asyncio.Event()
        spec = _SlowSpec("inv09b", done_event)
        handle = await rt.submit(spec)

        await rt.signal(handle, "approve", {"early": True})

        try:
            payload = await asyncio.wait_for(rt.await_signal(handle, "approve"), timeout=1.0)
        finally:
            done_event.set()

        assert payload == {"early": True}, (
            "Pre-delivered signal must be returned immediately; "
            "await_signal must drain the existing queue before suspending."
        )

    asyncio.run(_run())


def test_inv09_multiple_signals_fifo() -> None:
    """INV-09c: two signals delivered, two awaits return them in FIFO order.

    Failure mode if invariant slips: queue is replaced by latest-wins single
        slot → first signal payload is dropped. post_advisory_composer's
        replay path would lose the first approval if a duplicate signal
        arrives before the workflow processes the first.
    Catches: Patch 1.7 (asyncio.Queue is FIFO by construction).
    Temporal-readiness: TEMPORAL-READY — Temporal signal channel preserves
        per-signal-name FIFO order.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        done_event = asyncio.Event()
        spec = _SlowSpec("inv09c", done_event)
        handle = await rt.submit(spec)

        await rt.signal(handle, "tick", {"n": 1})
        await rt.signal(handle, "tick", {"n": 2})

        try:
            p1 = await asyncio.wait_for(rt.await_signal(handle, "tick"), 1.0)
            p2 = await asyncio.wait_for(rt.await_signal(handle, "tick"), 1.0)
        finally:
            done_event.set()

        assert (p1, p2) == ({"n": 1}, {"n": 2})

    asyncio.run(_run())


def test_inv09_await_signal_unknown_actor_raises() -> None:
    """INV-09d: await_signal on unknown workflow_id raises ActorNotFoundError.

    Failure mode if invariant slips: bare KeyError or — worse — silently
        creates an empty queue and blocks forever (a never-set asyncio.Queue
        with no producer). This is the "block forever" hazard that the
        docstring explicitly forbids.
    Catches: Patch 1.7 (await_signal entry-time existence check raises
        ActorNotFoundError).
    Temporal-readiness: TEMPORAL-READY — TemporalRuntime calls
        client.describe_workflow before subscribing to the signal channel;
        WorkflowNotFoundError → ActorNotFoundError per the wrapping contract.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        ghost = RunHandle(run_id="missing", workflow_id="missing")
        with pytest.raises(ActorNotFoundError):
            await rt.await_signal(ghost, "anything")

    asyncio.run(_run())


# ===========================================================================
# INV-09f (folded into INV-09) — Completed actor + empty queue raises
# ===========================================================================


def test_inv09_await_signal_completed_actor_raises() -> None:
    """INV-09f: await_signal on completed actor with empty queue raises ActorCompletedError.

    Failure mode if invariant slips: caller blocks forever — actor is done,
        no more signals will arrive. This was the UNDER-SPECIFIED gap I
        flagged in Pass-2; designer absorbed it as INV-09f / ActorCompletedError.
    Catches: Patch 1.7 (await_signal checks done_event.is_set() and q.empty()
        before suspending).
    Temporal-readiness: TEMPORAL-READY — TemporalRuntime calls describe()
        and inspects status=COMPLETED; if no buffered signal, raises
        ActorCompletedError.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        spec = _SimpleSpec("inv09f")  # no run() → completes immediately on submit
        handle = await rt.submit(spec)
        # Wait for completion event.
        await rt.await_result(handle)

        with pytest.raises(ActorCompletedError):
            await rt.await_signal(handle, "never_arrives")

    asyncio.run(_run())


# ===========================================================================
# INV-10 — get_handle eager existence check
# ===========================================================================


def test_inv10_get_handle_nonexistent_raises() -> None:
    """INV-10: get_handle(workflow_id) on missing id raises ActorNotFoundError.

    Failure mode if invariant slips: get_handle returns a fresh RunHandle
        wrapping a non-existent workflow_id. Consumer then calls signal/query
        and gets a delayed ActorNotFoundError (or worse, a hang). Eager check
        at handle-construction time prevents the dangling-handle anti-pattern.
    Catches: Patch 1.8 (new get_handle method on LocalRuntime + Runtime
        protocol).
    Temporal-readiness: TEMPORAL-READY but DIVERGENT-RETENTION — Temporal
        bounds existence by retention period (default 7d). LocalRuntime has no
        retention concept. Both raise ActorNotFoundError when truly absent;
        the *cause* is backend-specific.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        with pytest.raises(ActorNotFoundError):
            await rt.get_handle("never-existed")

        # Sanity: existing actor returns its handle.
        spec = _SimpleSpec("inv10-real")
        original = await rt.submit(spec)
        retrieved = await rt.get_handle("inv10-real")
        assert retrieved.run_id == original.run_id
        assert retrieved.workflow_id == original.workflow_id

    asyncio.run(_run())


# ===========================================================================
# HID-03 — Actor accumulation observable
# ===========================================================================


def test_hid03_actor_accumulation_observable() -> None:
    """HID-03: actor_ids() reflects unbounded growth; clear() resets to empty.

    Failure mode if invariant slips: silent leak — long-lived test fixtures
        accumulate stale handles. Without actor_ids(), the leak is
        unobservable; without clear(), tests cannot reset. Designer's Pass-3
        position: documentation-only invariant, but observability + reset are
        load-bearing test ergonomics.
    Catches: Patch 1.9 (actor_ids() + clear() test-only methods).
    Temporal-readiness: LOCAL-ONLY — actor_ids() is a test-only introspection
        method; Temporal's equivalent (list_workflows) requires admin RPC.
        clear() has no Temporal analogue (workflow termination + retention
        are the equivalents). Phase-2 marks this test `@local_only`.
    """

    async def _run() -> None:
        rt = LocalRuntime()
        N = 100
        for i in range(N):
            await rt.submit(_SimpleSpec(f"hid03-{i:04d}"))

        ids = rt.actor_ids()
        assert len(ids) == N
        assert sorted(ids) == sorted(f"hid03-{i:04d}" for i in range(N))

        rt.clear()
        assert rt.actor_ids() == []

        # After clear(), submitting the same workflow_id is allowed (state
        # was reset; INV-08 only catches duplicates within a runtime lifetime).
        h = await rt.submit(_SimpleSpec("hid03-0000"))
        assert h.workflow_id == "hid03-0000"

    asyncio.run(_run())
