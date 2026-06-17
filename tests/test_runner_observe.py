"""Runner observability wiring — the agent loop emits a trace tree.

A RecordingObserver captures the Observer calls the runner makes, so we assert
trace-per-run → span-per-iteration → generation-per-LLM-call → span-per-tool,
that the default observer is the zero-overhead NullObserver, and that errors
mark the trace + flush.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bene.ccr.runner import ClaudeCodeRunner, ModelResponse, ToolCall
from bene.config import runner_kwargs_from_config
from bene.core import Bene
from bene.router.tier import TierRouter


@pytest.fixture
def afs(tmp_path):
    fs = Bene(db_path=str(tmp_path / "obs.db"))
    yield fs
    fs.close()


@pytest.fixture
def mock_router():
    router = MagicMock(spec=TierRouter)
    router.route = AsyncMock()
    return router


class RecordingObservation:
    def __init__(self, log, kind, name):
        self.log = log
        self.kind = kind
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def span(self, name, *, input=None, metadata=None):
        self.log.append(("span", name))
        return RecordingObservation(self.log, "span", name)

    def generation(self, name, *, model=None, model_parameters=None, input=None, metadata=None):
        self.log.append(("generation", name))
        return RecordingObservation(self.log, "generation", name)

    def event(self, name, *, attributes=None):
        self.log.append(("event", name))

    def score(self, name, value, *, data_type="NUMERIC"):
        self.log.append(("score", name))

    def update(self, **fields):
        self.log.append(
            (
                "update",
                self.kind,
                self.name,
                fields.get("output"),
                fields.get("level"),
                fields.get("model"),
            )
        )

    def end(self, **fields):
        pass


class RecordingObserver:
    name = "recording"

    def __init__(self):
        self.log = []
        self.traces = []
        self.flushed = 0

    def trace(self, *, name, session_id=None, input=None, metadata=None, tags=None):
        self.log.append(("trace", name, session_id))
        self.traces.append((name, session_id))
        return RecordingObservation(self.log, "trace", name)

    def flush(self):
        self.flushed += 1

    def shutdown(self):
        pass


@pytest.mark.asyncio
async def test_emits_trace_and_generation_on_completion(afs, mock_router):
    mock_router.route.return_value = ModelResponse(
        content="done",
        tool_calls=[],
        stop_reason="end_turn",
        usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    )
    obs = RecordingObserver()
    ccr = ClaudeCodeRunner(afs, mock_router, observer=obs)
    aid = afs.spawn("obs-agent")

    result = await ccr.run_agent(aid, "do it")

    assert result == "done"
    assert obs.traces[0] == ("agent:obs-agent", aid)  # root → session_id = own id
    assert ("span", "iter-0") in obs.log
    assert ("generation", "llm-call") in obs.log
    # generation recorded the model output; trace recorded the final output
    assert any(e[0] == "update" and e[1] == "generation" and e[3] == "done" for e in obs.log)
    assert any(e[0] == "update" and e[1] == "trace" and e[3] == "done" for e in obs.log)
    assert obs.flushed == 1


@pytest.mark.asyncio
async def test_emits_one_tool_span_per_tool_call(afs, mock_router):
    mock_router.route.side_effect = [
        ModelResponse(
            content="setting state",
            tool_calls=[ToolCall(id="t1", name="state_set", input={"key": "k", "value": 1})],
            stop_reason="tool_use",
        ),
        ModelResponse(content="done", tool_calls=[], stop_reason="end_turn"),
    ]
    obs = RecordingObserver()
    ccr = ClaudeCodeRunner(afs, mock_router, observer=obs)
    aid = afs.spawn("tool-obs")

    result = await ccr.run_agent(aid, "use a tool")

    assert result == "done"
    assert ("span", "tool:state_set") in obs.log
    assert any(e[0] == "update" and e[1] == "span" and e[2] == "tool:state_set" for e in obs.log)
    # two LLM iterations → two iter spans + two generations
    assert obs.log.count(("generation", "llm-call")) == 2
    assert obs.log.count(("span", "iter-0")) == 1
    assert obs.log.count(("span", "iter-1")) == 1


@pytest.mark.asyncio
async def test_default_observer_is_null_and_behavior_unchanged(afs, mock_router, monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    mock_router.route.return_value = ModelResponse(
        content="ok", tool_calls=[], stop_reason="end_turn"
    )
    ccr = ClaudeCodeRunner(afs, mock_router)
    assert ccr.observer.name == "null"
    result = await ccr.run_agent(afs.spawn("default-obs"), "x")
    assert result == "ok"


@pytest.mark.asyncio
async def test_error_marks_trace_error_and_flushes(afs, mock_router):
    mock_router.route.side_effect = RuntimeError("boom")
    obs = RecordingObserver()
    ccr = ClaudeCodeRunner(afs, mock_router, observer=obs)

    with pytest.raises(RuntimeError, match="boom"):
        await ccr.run_agent(afs.spawn("err-obs"), "x")

    assert any(e[0] == "update" and e[1] == "trace" and e[4] == "ERROR" for e in obs.log)
    assert obs.flushed == 1


def test_observability_config_parsed_into_runner_kwargs():
    kwargs = runner_kwargs_from_config(
        {"kernel": {"observability": {"provider": "langfuse", "host": "http://x"}}}
    )
    assert kwargs["observability"] == {"provider": "langfuse", "host": "http://x"}


def test_runner_accepts_observability_kwarg(afs, mock_router, monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    ccr = ClaudeCodeRunner(afs, mock_router, observability={"provider": "none"})
    assert ccr.observer.name == "null"


@pytest.mark.asyncio
async def test_generation_records_model_for_cost_calc(afs, mock_router):
    # ModelResponse now carries model/model_parameters (plumbed from the router);
    # the runner forwards them to the generation observation for langfuse cost calc.
    mock_router.route.return_value = ModelResponse(
        content="done",
        tool_calls=[],
        stop_reason="end_turn",
        usage={"total_tokens": 5},
        model="claude-opus-4-8",
        model_parameters={"temperature": 0.1},
    )
    obs = RecordingObserver()
    ccr = ClaudeCodeRunner(afs, mock_router, observer=obs)
    await ccr.run_agent(afs.spawn("model-obs"), "x")

    # update tuple: (update, kind, name, output, level, model)
    assert any(
        e[0] == "update" and e[1] == "generation" and e[5] == "claude-opus-4-8" for e in obs.log
    )
