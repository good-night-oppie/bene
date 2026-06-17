"""End-to-end test for the BENE AgentWorkflow on the in-process Temporal env.

These tests are skipped automatically if ``temporalio`` isn't installed (it
ships under the optional ``[temporal]`` extra).
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("temporalio")

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from bene.storage.sqlite import SqliteStorage  # noqa: E402
from bene.temporal import runtime as bene_runtime  # noqa: E402
from bene.temporal.activities import ALL_ACTIVITIES  # noqa: E402
from bene.temporal.workflow import AgentInput, AgentWorkflow  # noqa: E402


@pytest.fixture
async def workflow_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture
async def store(tmp_path):
    s = SqliteStorage(db_path=str(tmp_path / "bene-temporal-test.db"))
    try:
        yield s
    finally:
        await s.close()


async def _llm_finish(model, prompt, agent_id):
    return {"finish": True, "output": f"echo({prompt})"}


async def _llm_two_step(model, prompt, agent_id):
    """Returns a tool_call on first invocation, then finishes."""
    if "[tool" in prompt:
        return {"finish": True, "output": "all done"}
    return {"tool_call": {"name": "noop", "input": {"x": 1}}}


async def _tool_handler(tool, input_data):
    return {"tool": tool, "in": input_data, "out": "ok"}


async def test_single_step_finish(workflow_env: WorkflowEnvironment, store):
    bene_runtime.configure(
        storage=store,
        blobs=store.blobs,
        llm_handler=_llm_finish,
        tool_handler=_tool_handler,
    )

    queue = f"bene-test-{uuid.uuid4().hex[:8]}"
    async with Worker(
        workflow_env.client,
        task_queue=queue,
        workflows=[AgentWorkflow],
        activities=ALL_ACTIVITIES,  # type: ignore[arg-type]
    ):
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        result = await workflow_env.client.execute_workflow(
            AgentWorkflow.run,
            AgentInput(agent_id=agent_id, name="finish-test", prompt="hi"),
            id=agent_id,
            task_queue=queue,
        )

    assert result.status == "completed"
    assert result.steps == 1
    info = await store.status(agent_id)
    assert info["status"] == "completed"

    events = await store.get_events(agent_id)
    types = {e["event_type"] for e in events}
    assert "agent_spawn" in types
    assert "llm_call" in types
    assert "agent_completed" in types


async def test_tool_call_loop(workflow_env: WorkflowEnvironment, store):
    bene_runtime.configure(
        storage=store,
        blobs=store.blobs,
        llm_handler=_llm_two_step,
        tool_handler=_tool_handler,
    )

    queue = f"bene-test-{uuid.uuid4().hex[:8]}"
    async with Worker(
        workflow_env.client,
        task_queue=queue,
        workflows=[AgentWorkflow],
        activities=ALL_ACTIVITIES,  # type: ignore[arg-type]
    ):
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        result = await workflow_env.client.execute_workflow(
            AgentWorkflow.run,
            AgentInput(
                agent_id=agent_id,
                name="tool-loop-test",
                prompt="solve",
                max_steps=4,
            ),
            id=agent_id,
            task_queue=queue,
        )

    assert result.status == "completed"
    assert result.steps == 2

    calls = await store.get_tool_calls(agent_id)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "noop"
    assert calls[0]["status"] == "success"


async def test_kill_signal_stops_loop(workflow_env: WorkflowEnvironment, store):
    """Killed workflow should write a final 'agent_killed' event and stop."""

    async def slow_llm(model, prompt, agent_id):
        # Always return a tool_call so the loop continues until killed.
        return {"tool_call": {"name": "noop", "input": {}}}

    bene_runtime.configure(
        storage=store,
        blobs=store.blobs,
        llm_handler=slow_llm,
        tool_handler=_tool_handler,
    )

    queue = f"bene-test-{uuid.uuid4().hex[:8]}"
    async with Worker(
        workflow_env.client,
        task_queue=queue,
        workflows=[AgentWorkflow],
        activities=ALL_ACTIVITIES,  # type: ignore[arg-type]
    ):
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        handle = await workflow_env.client.start_workflow(
            AgentWorkflow.run,
            AgentInput(
                agent_id=agent_id,
                name="kill-test",
                prompt="loop",
                max_steps=50,
            ),
            id=agent_id,
            task_queue=queue,
        )
        # Give the workflow time to start; then kill it.
        await handle.signal(AgentWorkflow.kill)
        result = await handle.result()

    assert result.status == "killed"
    info = await store.status(agent_id)
    assert info["status"] == "killed"
