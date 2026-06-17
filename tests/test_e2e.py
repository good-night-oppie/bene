"""End-to-end tests for BENE/Bene (no real LLM required)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bene.core import Bene
from bene.ccr.runner import ClaudeCodeRunner, ModelResponse, ToolCall
from bene.kernel.memory import ContextOS
from bene.router.tier import TierRouter


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "test_e2e.db")
    fs = Bene(db_path=db_path)
    yield fs
    fs.close()


@pytest.fixture
def mock_router():
    """Create a mock Tier router that returns predefined responses."""
    router = MagicMock(spec=TierRouter)
    router.route = AsyncMock()
    return router


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_simple_agent_run(self, afs: Bene, mock_router):
        """Agent receives a task and completes with a text response."""
        mock_router.route.return_value = ModelResponse(
            content="Task completed successfully!",
            tool_calls=[],
            stop_reason="end_turn",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )

        ccr = ClaudeCodeRunner(afs, mock_router)
        agent_id = afs.spawn("simple-agent")

        result = await ccr.run_agent(agent_id, "Do something simple")

        assert result == "Task completed successfully!"
        assert afs.status(agent_id)["status"] == "completed"
        assert afs.get_state(agent_id, "result") == "Task completed successfully!"

    @pytest.mark.asyncio
    async def test_agent_with_tool_calls(self, afs: Bene, mock_router):
        """Agent uses tools and then completes."""
        # First response: tool call
        mock_router.route.side_effect = [
            ModelResponse(
                content="Let me write a file.",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="fs_write",
                        input={"path": "/output.txt", "content": "hello"},
                    ),
                ],
                stop_reason="tool_use",
            ),
            # Second response: done
            ModelResponse(
                content="I wrote the file.",
                tool_calls=[],
                stop_reason="end_turn",
            ),
        ]

        ccr = ClaudeCodeRunner(afs, mock_router)
        agent_id = afs.spawn("tool-agent")

        result = await ccr.run_agent(agent_id, "Write a file")

        assert result == "I wrote the file."
        assert afs.read(agent_id, "/output.txt") == b"hello"
        assert afs.status(agent_id)["status"] == "completed"

    @pytest.mark.asyncio
    async def test_agent_tool_error_handling(self, afs: Bene, mock_router):
        """Agent handles tool errors gracefully."""
        mock_router.route.side_effect = [
            ModelResponse(
                content="Reading a file.",
                tool_calls=[
                    ToolCall(id="tc-1", name="fs_read", input={"path": "/nonexistent.txt"}),
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(
                content="The file doesn't exist, so I'm done.",
                tool_calls=[],
                stop_reason="end_turn",
            ),
        ]

        ccr = ClaudeCodeRunner(afs, mock_router)
        agent_id = afs.spawn("error-agent")

        result = await ccr.run_agent(agent_id, "Read a nonexistent file")
        assert "doesn't exist" in result

        # Verify the error was logged
        calls = afs.get_tool_calls(agent_id, status="error")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_parallel_agents(self, afs: Bene, mock_router):
        """Multiple agents run in parallel."""
        mock_router.route.return_value = ModelResponse(
            content="Done!",
            tool_calls=[],
            stop_reason="end_turn",
        )

        ccr = ClaudeCodeRunner(afs, mock_router)

        results = await ccr.run_parallel(
            [
                {"name": "agent-1", "prompt": "Task 1"},
                {"name": "agent-2", "prompt": "Task 2"},
                {"name": "agent-3", "prompt": "Task 3"},
            ]
        )

        assert len(results) == 3
        assert all(r == "Done!" for r in results)

        # All agents should be completed
        agents = afs.list_agents(status_filter="completed")
        assert len(agents) == 3

    @pytest.mark.asyncio
    async def test_checkpoint_during_execution(self, afs: Bene, mock_router):
        """Agent auto-checkpoints during execution."""
        # Create enough iterations to trigger checkpoint
        responses = []
        for i in range(11):
            responses.append(
                ModelResponse(
                    content=f"Step {i}",
                    tool_calls=[
                        ToolCall(id=f"tc-{i}", name="state_set", input={"key": "step", "value": i}),
                    ],
                    stop_reason="tool_use",
                )
            )
        responses.append(ModelResponse(content="All done", tool_calls=[], stop_reason="end_turn"))
        mock_router.route.side_effect = responses

        ccr = ClaudeCodeRunner(afs, mock_router, checkpoint_interval=5)
        agent_id = afs.spawn("cp-agent")

        await ccr.run_agent(agent_id, "Do many steps")

        # Should have auto-checkpoints
        cps = afs.list_checkpoints(agent_id)
        assert len(cps) >= 1

    @pytest.mark.asyncio
    async def test_agent_state_persistence(self, afs: Bene, mock_router):
        """Agent state persists across iterations."""
        mock_router.route.side_effect = [
            ModelResponse(
                content="Setting state",
                tool_calls=[
                    ToolCall(id="tc-1", name="state_set", input={"key": "progress", "value": 50}),
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(
                content="Checking state",
                tool_calls=[
                    ToolCall(id="tc-2", name="state_get", input={"key": "progress"}),
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(content="Done", tool_calls=[], stop_reason="end_turn"),
        ]

        ccr = ClaudeCodeRunner(afs, mock_router)
        agent_id = afs.spawn("state-agent")

        await ccr.run_agent(agent_id, "Track progress")

        assert afs.get_state(agent_id, "progress") == 50

    @pytest.mark.asyncio
    async def test_context_os_packing_is_opt_in_for_runner(self, afs: Bene, mock_router):
        """Opt-in ContextOS packing trims older tool blocks before model calls."""
        mock_router.route.side_effect = [
            ModelResponse(
                content="old block",
                tool_calls=[
                    ToolCall(
                        id="tc-old",
                        name="state_set",
                        input={"key": "phase", "value": "old"},
                    )
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(
                content="new block",
                tool_calls=[
                    ToolCall(
                        id="tc-new",
                        name="state_set",
                        input={"key": "phase", "value": "new"},
                    )
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(content="done", tool_calls=[], stop_reason="end_turn"),
        ]

        ccr = ClaudeCodeRunner(
            afs,
            mock_router,
            context_packing_enabled=True,
            context_budget_tokens=3,
            context_os=ContextOS(estimator=lambda _text: 1),
            loop_guard_enabled=False,
        )
        agent_id = afs.spawn("context-agent")

        await ccr.run_agent(agent_id, "Track only the recent block")

        third_call_messages = mock_router.route.call_args_list[2].kwargs["messages"]
        encoded = str(third_call_messages)
        assert "tc-new" in encoded
        assert "tc-old" not in encoded

        manifest = afs.get_state(agent_id, "context_os_manifest")
        assert manifest["budget_tokens"] == 3
        assert manifest["estimated_tokens"] <= 3
        assert manifest["dropped"]

    @pytest.mark.asyncio
    async def test_loop_guard_blocks_repeated_tool_call(self, afs: Bene, mock_router):
        """Runner wires LoopGuard into tool execution and records intervention engrams."""

        def repeated_call(i: int) -> ToolCall:
            return ToolCall(
                id=f"tc-repeat-{i}",
                name="state_set",
                input={"key": "same", "value": 1},
            )

        mock_router.route.side_effect = [
            ModelResponse(content="first", tool_calls=[repeated_call(1)], stop_reason="tool_use"),
            ModelResponse(content="second", tool_calls=[repeated_call(2)], stop_reason="tool_use"),
            ModelResponse(content="third", tool_calls=[repeated_call(3)], stop_reason="tool_use"),
            ModelResponse(content="done", tool_calls=[], stop_reason="end_turn"),
        ]

        ccr = ClaudeCodeRunner(afs, mock_router, loop_guard_repeat_threshold=3)
        agent_id = afs.spawn("loop-agent")

        await ccr.run_agent(agent_id, "Keep setting the same state")

        calls = afs.get_tool_calls(agent_id)
        statuses = [call["status"] for call in calls]
        assert statuses.count("success") == 2
        assert statuses.count("error") == 1
        assert afs.get_state(agent_id, "same") == 1

        conversation = afs.get_state(agent_id, "conversation")
        assert any("LOOP GUARD" in msg.get("content", "") for msg in conversation)

        rows = afs.query("SELECT kind, title FROM engrams WHERE kind='intervention'")
        assert rows == [{"kind": "intervention", "title": "loop-guard:repetition"}]


class TestFullWorkflow:
    """Integration tests that exercise the complete workflow."""

    def test_spawn_checkpoint_restore_cycle(self, afs: Bene):
        agent_id = afs.spawn("workflow-test")

        # Phase 1: create some files and state
        afs.write(agent_id, "/src/app.py", b"print('v1')")
        afs.write(agent_id, "/tests/test_app.py", b"def test(): pass")
        afs.set_state(agent_id, "phase", "initial")
        cp1 = afs.checkpoint(agent_id, label="phase-1")

        # Phase 2: modify
        afs.write(agent_id, "/src/app.py", b"print('v2')")
        afs.write(agent_id, "/src/utils.py", b"def helper(): pass")
        afs.set_state(agent_id, "phase", "modified")
        cp2 = afs.checkpoint(agent_id, label="phase-2")

        # Diff
        diff = afs.diff_checkpoints(agent_id, cp1, cp2)
        assert "/src/app.py" in diff["files"]["modified"]
        assert "/src/utils.py" in diff["files"]["added"]

        # Restore to phase 1
        afs.restore(agent_id, cp1)
        assert afs.read(agent_id, "/src/app.py") == b"print('v1')"
        assert afs.get_state(agent_id, "phase") == "initial"
        assert not afs.exists(agent_id, "/src/utils.py")

    def test_multi_agent_isolation_and_audit(self, afs: Bene):
        """Multiple agents work in parallel with full audit trail."""
        agents = [
            afs.spawn("agent-alpha"),
            afs.spawn("agent-beta"),
            afs.spawn("agent-gamma"),
        ]

        for agent_id in agents:
            afs.write(agent_id, "/output.txt", f"output from {agent_id}".encode())
            afs.log_tool_call(agent_id, "fs_write", {"path": "/output.txt"})
            afs.set_state(agent_id, "completed", True)

        # Query audit trail
        results = afs.query(
            "SELECT agent_id, COUNT(*) as event_count FROM events GROUP BY agent_id"
        )
        assert len(results) == 3
        for r in results:
            assert r["event_count"] >= 2  # spawn + file_write at minimum

        # Query token usage
        tool_results = afs.query("SELECT agent_id, tool_name FROM tool_calls ORDER BY agent_id")
        assert len(tool_results) == 3
