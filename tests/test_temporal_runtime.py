"""TemporalRuntime tests — Runtime Protocol parity with LocalRuntime.

Skipped automatically if ``temporalio`` isn't installed (optional extra).

Each test exercises the same Runtime Protocol surface on TemporalRuntime
that LocalRuntime tests cover, ensuring drop-in equivalence for consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

pytest.importorskip("temporalio")

from temporalio import workflow  # noqa: E402
from temporalio.client import Client  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from bene.runtime.core import (  # noqa: E402
    CostEstimate,
    ReconciliationStrategy,
    SideEffectKind,
    SideEffectLabel,
)
from bene.runtime.exceptions import (  # noqa: E402
    ActorAlreadyRunningError,
    ActorNotFoundError,
)
from bene.runtime.handle import (  # noqa: E402, F401
    RunHandle,
    Runtime,
    TypedQuery,
)
from bene.temporal.runtime_impl import TemporalRuntime  # noqa: E402


TASK_QUEUE = "test-bene-runtime"


# ---------------------------------------------------------------------------
# Minimal test workflow + spec
# ---------------------------------------------------------------------------


@dataclass
class EchoInput:
    payload: str
    grow_via_signal: bool = False


@workflow.defn(name="EchoWorkflow")
class EchoWorkflow:
    """Trivial workflow used to exercise Runtime Protocol surface.

    Records signals, exposes them via query, and either returns immediately
    or waits for a "finish" signal before completing.
    """

    def __init__(self) -> None:
        self._signals: list[tuple[str, Any]] = []
        self._done: bool = False

    @workflow.run
    async def run(self, inp: EchoInput) -> str:
        if not inp.grow_via_signal:
            return f"echo:{inp.payload}"
        await workflow.wait_condition(lambda: self._done)
        return f"echo:{inp.payload}:signals={len(self._signals)}"

    @workflow.signal(name="record")
    def record(self, payload: Any) -> None:
        self._signals.append(("record", payload))

    @workflow.signal(name="finish")
    def finish(self, _payload: Any = None) -> None:
        self._done = True

    @workflow.query(name="signal_count")
    def signal_count(self) -> int:
        return len(self._signals)


@workflow.defn(name="FailingWorkflow")
class FailingWorkflow:
    """Workflow that raises ApplicationError on run.

    Used to exercise the await_result failure-unwrap contract: Temporal wraps
    the raised ApplicationError in WorkflowFailureError; the runtime must
    unwrap to the original cause so consumers see a stable type.
    """

    @workflow.run
    async def run(self, message: str) -> str:
        from temporalio.exceptions import ApplicationError

        raise ApplicationError(message, type="TestFailure")


@dataclass
class EchoSpec:
    """Backend-portable spec for both LocalRuntime and TemporalRuntime.

    LocalRuntime ignores ``workflow_class`` + ``input``; TemporalRuntime ignores
    ``run``. Consumers writing portable code populate both.
    """

    workflow_id: str
    workflow_class: type = EchoWorkflow
    input: EchoInput | None = None
    run: Any = None  # LocalRuntime hook, unused here


@dataclass
class FailingSpec:
    workflow_id: str
    workflow_class: type = FailingWorkflow
    input: str = "boom"
    run: Any = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture
async def client(env: WorkflowEnvironment) -> Client:
    return env.client


@pytest.fixture
async def worker(env: WorkflowEnvironment, client: Client):
    """Spin up a Temporal worker bound to the test env on TASK_QUEUE."""
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[EchoWorkflow, FailingWorkflow],
    ):
        yield


@pytest.fixture
def runtime(client: Client) -> Runtime:
    """Construct concretely; expose as the Runtime Protocol so tests double
    as a copy-paste template for portable consumer code (pillar #3 / #4)."""
    return TemporalRuntime(client=client, task_queue=TASK_QUEUE)


# ---------------------------------------------------------------------------
# submit / await_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_returns_handle_immediately(worker, runtime: Runtime) -> None:
    spec = EchoSpec(workflow_id="echo-1", input=EchoInput(payload="hello"))
    handle = await runtime.submit(spec)
    assert isinstance(handle, RunHandle)
    assert handle.workflow_id == "echo-1"


@pytest.mark.asyncio
async def test_await_result_returns_workflow_output(worker, runtime: Runtime) -> None:
    spec = EchoSpec(workflow_id="echo-2", input=EchoInput(payload="world"))
    handle = await runtime.submit(spec)
    result = await runtime.await_result(handle)
    assert result == "echo:world"


@pytest.mark.asyncio
async def test_await_result_failed_workflow_unwraps_application_error(
    worker, runtime: Runtime
) -> None:
    """Pin INV-07: a failed workflow must surface its ApplicationError cause,
    not a Temporal-specific WorkflowFailureError envelope. Consumers writing
    against the Runtime Protocol should never see ``temporalio.*`` exception
    types — that breaks pillar #3 (Protocol-portable, not concrete-bound).
    """
    from temporalio.exceptions import ApplicationError

    spec = FailingSpec(workflow_id="failing-1")
    handle = await runtime.submit(spec)
    with pytest.raises(ApplicationError, match="boom"):
        await runtime.await_result(handle)


@pytest.mark.asyncio
async def test_submit_without_workflow_class_raises(runtime: Runtime) -> None:
    @dataclass
    class BadSpec:
        workflow_id: str = "x"

    with pytest.raises(ValueError, match="workflow_class"):
        await runtime.submit(BadSpec())


@pytest.mark.asyncio
async def test_submit_duplicate_workflow_id_raises(worker, runtime: Runtime) -> None:
    spec = EchoSpec(workflow_id="echo-dup", input=EchoInput(payload="x", grow_via_signal=True))
    await runtime.submit(spec)
    with pytest.raises(ActorAlreadyRunningError):
        await runtime.submit(spec)


# ---------------------------------------------------------------------------
# signal / query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signal_delivered_and_visible_via_query(worker, runtime: Runtime) -> None:
    spec = EchoSpec(
        workflow_id="echo-sig",
        input=EchoInput(payload="x", grow_via_signal=True),
    )
    handle = await runtime.submit(spec)
    await runtime.signal(handle, "record", {"k": 1})
    await runtime.signal(handle, "record", {"k": 2})

    count = await runtime.query(handle, TypedQuery("signal_count", int))
    assert count == 2

    await runtime.signal(handle, "finish", None)
    result = await runtime.await_result(handle)
    assert result == "echo:x:signals=2"


@pytest.mark.asyncio
async def test_signal_unknown_workflow_raises_actor_not_found(worker, runtime: Runtime) -> None:
    handle = RunHandle(run_id="missing", workflow_id="missing")
    with pytest.raises(ActorNotFoundError):
        await runtime.signal(handle, "record", {})


# ---------------------------------------------------------------------------
# get_handle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_handle_known_workflow(worker, runtime: Runtime) -> None:
    spec = EchoSpec(
        workflow_id="echo-gh",
        input=EchoInput(payload="x", grow_via_signal=True),
    )
    await runtime.submit(spec)
    h = await runtime.get_handle("echo-gh")
    assert h.workflow_id == "echo-gh"
    await runtime.signal(h, "finish", None)


@pytest.mark.asyncio
async def test_get_handle_missing_raises(runtime: Runtime) -> None:
    with pytest.raises(ActorNotFoundError):
        await runtime.get_handle("does-not-exist-xyz")


# ---------------------------------------------------------------------------
# start_or_signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_or_signal_starts_new(worker, runtime: Runtime) -> None:
    spec = EchoSpec(
        workflow_id="echo-sos",
        input=EchoInput(payload="x", grow_via_signal=True),
    )
    handle = await runtime.start_or_signal(spec, "record", {"v": "first"})
    count = await runtime.query(handle, TypedQuery("signal_count", int))
    assert count == 1
    await runtime.signal(handle, "finish", None)


@pytest.mark.asyncio
async def test_start_or_signal_signals_existing_running(worker, runtime: Runtime) -> None:
    """Calling start_or_signal twice on a running workflow must signal the
    existing run (not raise WorkflowAlreadyStartedError). Pins the contract
    the v1 PR landed without test coverage — Temporal's signal-with-start
    raises if a RUNNING workflow already exists, so the runtime must catch
    and signal the existing handle.
    """
    spec = EchoSpec(
        workflow_id="echo-sos-existing",
        input=EchoInput(payload="x", grow_via_signal=True),
    )
    first = await runtime.start_or_signal(spec, "record", {"v": "first"})
    second = await runtime.start_or_signal(spec, "record", {"v": "second"})
    # Both calls return a handle for the same workflow_id.
    assert first.workflow_id == second.workflow_id == "echo-sos-existing"
    # Both signals landed on the same instance.
    count = await runtime.query(first, TypedQuery("signal_count", int))
    assert count == 2
    await runtime.signal(first, "finish", None)
    result = await runtime.await_result(first)
    assert result == "echo:x:signals=2"


# ---------------------------------------------------------------------------
# await_signal — Phase-2.x stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_await_signal_raises_not_implemented(runtime: Runtime) -> None:
    handle = RunHandle(run_id="x", workflow_id="x")
    with pytest.raises(NotImplementedError, match="Phase-2.x"):
        await runtime.await_signal(handle, "any")


# ---------------------------------------------------------------------------
# submit_side_effect — cost validation + delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_side_effect_executes_callable(runtime: Runtime) -> None:
    label = SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_READ,
        semantic_class="test.read",
        rate_limit_class="test",
        cost_estimate=CostEstimate(confirmed_free=True),
    )

    async def op() -> str:
        return "executed"

    result = await runtime.submit_side_effect(label, ("k",), op)
    assert result == "executed"


@pytest.mark.asyncio
async def test_submit_side_effect_external_write_zero_cost_raises(
    runtime: Runtime,
) -> None:
    label = SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_WRITE,
        semantic_class="test.write",
        rate_limit_class="test",
        cost_estimate=CostEstimate(),  # zero, not confirmed_free
        reconciliation_strategy=ReconciliationStrategy.IDEMPOTENT_BY_KEY,
    )

    async def op() -> None:
        pytest.fail("execute_fn must not run when validation fails")

    with pytest.raises(ValueError, match="explicit cost_estimate"):
        await runtime.submit_side_effect(label, ("k",), op)


@pytest.mark.asyncio
async def test_submit_side_effect_external_write_no_reconciliation_warns(
    runtime: Runtime,
) -> None:
    label = SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_WRITE,
        semantic_class="test.write",
        rate_limit_class="test",
        cost_estimate=CostEstimate(latency_ms=100),
        reconciliation_strategy=None,
    )

    async def op() -> str:
        return "ran"

    with pytest.warns(UserWarning, match="reconciliation_strategy=None"):
        result = await runtime.submit_side_effect(label, ("k",), op)
    assert result == "ran"


@pytest.mark.asyncio
async def test_submit_side_effect_negative_cost_raises(runtime: Runtime) -> None:
    label = SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_WRITE,
        semantic_class="test.write",
        rate_limit_class="test",
        cost_estimate=CostEstimate(latency_ms=-1),
        reconciliation_strategy=ReconciliationStrategy.IDEMPOTENT_BY_KEY,
    )

    async def op() -> None:
        pytest.fail("execute_fn must not run")

    with pytest.raises(ValueError, match="non-negative"):
        await runtime.submit_side_effect(label, ("k",), op)
