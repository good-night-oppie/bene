"""BENE :class:`AgentWorkflow` — the deterministic agent loop.

A single Workflow instance corresponds to a single BENE agent. The workflow
owns:

* lifecycle (spawn -> running -> completed/killed)
* the agent-side decision loop (LLM -> tool -> LLM ...)
* signals for ``pause``/``resume``/``kill``
* queries for ``status`` and ``current_step``

Every side effect lives in an Activity (see :mod:`bene.temporal.activities`).
``continue_as_new`` is used when the history grows past ~45K events to keep
long-lived agents fast to replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from bene.temporal.activities import (
        call_llm,
        complete_agent,
        create_checkpoint,
        log_event,
        run_tool,
        set_status,
        spawn_agent,
        write_vfs,
    )


@dataclass
class AgentInput:
    """Workflow input — fully serializable."""

    agent_id: str
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    model: str = "echo"
    max_steps: int = 20


@dataclass
class AgentResult:
    agent_id: str
    status: str
    steps: int
    last_output: Any = None


_LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
    non_retryable_error_types=["InvalidPromptError"],
)

_FAST_RETRY = RetryPolicy(
    initial_interval=timedelta(milliseconds=200),
    maximum_attempts=10,
)

_HISTORY_BUDGET = 45_000


@workflow.defn(name="BeneAgentWorkflow")
class AgentWorkflow:
    """Durable execution of one BENE agent."""

    def __init__(self) -> None:
        self._paused: bool = False
        self._killed: bool = False
        self._status: str = "initialized"
        self._step: int = 0
        self._last_output: Any = None

    # ── Signals ──────────────────────────────────────────────────────

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def kill(self) -> None:
        self._killed = True

    # ── Queries ──────────────────────────────────────────────────────

    @workflow.query
    def status(self) -> str:
        return self._status

    @workflow.query
    def current_step(self) -> int:
        return self._step

    @workflow.query
    def last_output(self) -> Any:
        return self._last_output

    # ── Run ──────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, payload: AgentInput) -> AgentResult:
        await workflow.execute_activity(
            spawn_agent,
            args=[
                payload.name,
                payload.config,
                payload.parent_id,
                payload.metadata,
                payload.agent_id,
            ],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_FAST_RETRY,
        )
        await workflow.execute_activity(
            set_status,
            args=[payload.agent_id, "running", None],
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=_FAST_RETRY,
        )
        self._status = "running"

        max_steps = payload.config.get("max_steps", payload.max_steps)
        prompt = payload.prompt

        while self._step < max_steps and not self._killed:
            await workflow.wait_condition(lambda: not self._paused or self._killed)
            if self._killed:
                break

            step_key = f"{workflow.info().workflow_id}:step:{self._step}"
            llm_out = await workflow.execute_activity(
                call_llm,
                args=[payload.model, prompt, payload.agent_id, step_key + ":llm"],
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=_LLM_RETRY,
            )
            self._last_output = llm_out

            tool_call = llm_out.get("tool_call")
            if tool_call:
                tool_result = await workflow.execute_activity(
                    run_tool,
                    args=[
                        payload.agent_id,
                        tool_call["name"],
                        tool_call.get("input", {}),
                        step_key + ":tool",
                    ],
                    start_to_close_timeout=timedelta(minutes=2),
                    heartbeat_timeout=timedelta(seconds=15),
                    retry_policy=_FAST_RETRY,
                )
                self._last_output = tool_result
                # Feed tool result back into the prompt for the next round
                prompt = f"{prompt}\n[tool {tool_call['name']} returned] {tool_result}"

            if llm_out.get("write"):
                file_spec = llm_out["write"]
                await workflow.execute_activity(
                    write_vfs,
                    args=[
                        payload.agent_id,
                        file_spec["path"],
                        file_spec["content"].encode()
                        if isinstance(file_spec["content"], str)
                        else file_spec["content"],
                        step_key + ":vfs",
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_FAST_RETRY,
                )

            await workflow.execute_activity(
                log_event,
                args=[
                    payload.agent_id,
                    "agent_step",
                    {"step": self._step, "phase": "complete"},
                    step_key + ":step_event",
                ],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=_FAST_RETRY,
            )

            self._step += 1

            if llm_out.get("finish"):
                break

            # Bound history for long-lived agents.
            if workflow.info().get_current_history_length() > _HISTORY_BUDGET and not llm_out.get(
                "finish"
            ):
                # Capture a checkpoint then continue-as-new with refreshed input.
                await workflow.execute_activity(
                    create_checkpoint,
                    args=[payload.agent_id, f"continue_as_new@step={self._step}"],
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=_FAST_RETRY,
                )
                # Mark the resume boundary so crash/recovery analysis can
                # distinguish a continue_as_new fork from a worker restart.
                # Idempotency key includes the step so a Temporal-side
                # workflow-task retry across the boundary doesn't double-count.
                await workflow.execute_activity(
                    log_event,
                    args=[
                        payload.agent_id,
                        "agent_resumed",
                        {"reason": "history_budget", "step": self._step},
                        step_key + ":resumed",
                    ],
                    start_to_close_timeout=timedelta(seconds=5),
                    retry_policy=_FAST_RETRY,
                )
                workflow.continue_as_new(
                    AgentInput(
                        agent_id=payload.agent_id,
                        name=payload.name,
                        config=payload.config,
                        parent_id=payload.parent_id,
                        metadata=payload.metadata,
                        prompt=prompt,
                        model=payload.model,
                        max_steps=max_steps - self._step,
                    )
                )

        final_status = "killed" if self._killed else "completed"
        await workflow.execute_activity(
            complete_agent,
            args=[
                payload.agent_id,
                final_status,
                {"steps": self._step, "last_output": str(self._last_output)[:500]},
            ],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_FAST_RETRY,
        )
        self._status = final_status

        return AgentResult(
            agent_id=payload.agent_id,
            status=final_status,
            steps=self._step,
            last_output=self._last_output,
        )
