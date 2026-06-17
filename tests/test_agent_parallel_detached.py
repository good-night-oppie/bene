"""Tests for the detached agent_parallel MCP handler.

Closes #8 Problem A: agent_parallel used to await `run_parallel` inside the
MCP request, so any RCA that took longer than the host's MCP timeout (5min
for Claude Code) was killed from the caller side while the bene agents
were still running. The fix mirrors `mh_search`'s detached-worker pattern:
spawn agents synchronously (cheap DB writes), launch a detached worker
process to drive them, and return agent_ids + pid immediately.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bene.core import Bene
from bene.ccr.runner import ClaudeCodeRunner
from bene.mcp import server as mcp_server


@pytest.fixture
def initialized_server(tmp_path):
    """Initialize the MCP server module with a real Bene DB and stub runner."""
    db_path = tmp_path / "bene.db"
    afs = Bene(db_path=str(db_path))

    # Stub router — agent_parallel detached worker is independent of router.
    router = MagicMock()
    runner = ClaudeCodeRunner(afs=afs, router=router)

    mcp_server._afs = afs
    mcp_server._ccr = runner
    yield afs, runner, tmp_path
    mcp_server._afs = None
    mcp_server._ccr = None


async def test_agent_parallel_returns_immediately_with_agent_ids(initialized_server):
    """The handler must return agent_ids + pid synchronously; it must NOT
    block on the agents' completion. We assert by patching subprocess.Popen
    and verifying we never called run_parallel."""
    afs, runner, tmp_path = initialized_server

    fake_proc = MagicMock(pid=99999)

    with (
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(runner, "run_parallel") as mock_run_parallel,
    ):
        result_json = await mcp_server._dispatch(
            "agent_parallel",
            {
                "tasks": [
                    {"name": "rca_ofs_a", "prompt": "RCA bug A"},
                    {"name": "rca_ofs_b", "prompt": "RCA bug B"},
                ]
            },
        )

    result = json.loads(result_json)

    # New contract
    assert result["status"] == "running", f"expected status=running, got {result!r}"
    assert "agent_ids" in result and len(result["agent_ids"]) == 2
    assert result["pid"] == 99999
    assert "log_path" in result

    # Old behavior: handler awaited run_parallel inline. Must not happen.
    mock_run_parallel.assert_not_called()
    # Detached worker subprocess must be launched.
    mock_popen.assert_called_once()


async def test_agent_parallel_spawns_agents_before_returning(initialized_server):
    """Agents must exist in the DB by the time the handler returns,
    so callers can poll via agent_status immediately."""
    afs, runner, tmp_path = initialized_server

    with patch("subprocess.Popen", return_value=MagicMock(pid=12345)):
        result_json = await mcp_server._dispatch(
            "agent_parallel",
            {"tasks": [{"name": "worker_x", "prompt": "do x"}]},
        )

    result = json.loads(result_json)
    agent_id = result["agent_ids"][0]

    # agent_status returns a dict; the row must exist.
    info = afs.status(agent_id)
    assert info["name"] == "worker_x"


async def test_agent_parallel_writes_task_spec_for_worker(initialized_server):
    """The detached worker needs a spec file (or stdin / argv) describing the
    pre-spawned agent_ids and prompts. Verify a spec is produced and is
    readable JSON."""
    afs, runner, tmp_path = initialized_server

    with patch("subprocess.Popen", return_value=MagicMock(pid=12345)) as mock_popen:
        await mcp_server._dispatch(
            "agent_parallel",
            {
                "tasks": [
                    {"name": "a", "prompt": "pa"},
                    {"name": "b", "prompt": "pb"},
                ]
            },
        )

    # Find the spec file path in the Popen argv (we don't care exactly
    # which CLI flag is used; just that some readable JSON spec exists
    # somewhere among the args).
    argv = mock_popen.call_args.args[0]
    spec_path = None
    for token in argv:
        if isinstance(token, str) and token.endswith(".json") and Path(token).exists():
            spec_path = token
            break
    assert spec_path is not None, f"no spec JSON file in argv: {argv}"
    spec = json.loads(Path(spec_path).read_text())
    assert isinstance(spec, list) and len(spec) == 2
    assert {t["prompt"] for t in spec} == {"pa", "pb"}
    assert all("agent_id" in t for t in spec)


def test_parallel_worker_module_is_importable():
    """The detached worker must exist as an importable module so subprocess
    launches it with python -m."""
    from bene.ccr import parallel_worker  # noqa: F401

    assert hasattr(parallel_worker, "main")


async def test_agent_parallel_rejects_malformed_tasks(initialized_server):
    """Malformed tasks must be rejected upfront, before any agent is spawned,
    so a bad request can't leave half-spawned orphan agents in the DB."""
    afs, _runner, _tmp_path = initialized_server

    bad_inputs = [
        {"tasks": "not a list"},
        {"tasks": []},
        {"tasks": [{"name": "ok"}]},  # missing prompt
        {"tasks": [{"prompt": "ok"}]},  # missing name
        {"tasks": [{"name": "ok", "prompt": "ok"}, "string instead of dict"]},
    ]
    for bad in bad_inputs:
        with pytest.raises((ValueError, TypeError, KeyError)):
            await mcp_server._dispatch("agent_parallel", bad)

        # Crucially: no spawned agents should remain after a rejected call.
        rows = afs.query(
            "SELECT COUNT(*) AS c FROM agents WHERE status NOT IN ('completed','failed','killed')"
        )
        assert rows[0]["c"] == 0, f"orphan agents found after rejected input {bad!r}: {rows}"


async def test_agent_parallel_cleans_up_on_spec_write_failure(initialized_server):
    """If the spec JSON write fails after agents are spawned, the handler must
    not leave those agents alive — they should be marked failed (or never
    have been pre-spawned) so callers don't poll forever on orphans."""
    afs, _runner, _tmp_path = initialized_server

    real_open = open

    def failing_open(path, *args, **kwargs):
        if isinstance(path, str) and path.endswith(".json"):
            raise OSError("simulated disk-full / permission failure")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=failing_open):
        with pytest.raises((OSError, RuntimeError)):
            await mcp_server._dispatch(
                "agent_parallel",
                {"tasks": [{"name": "a", "prompt": "pa"}, {"name": "b", "prompt": "pb"}]},
            )

    rows = afs.query(
        "SELECT COUNT(*) AS c FROM agents WHERE status NOT IN ('completed','failed','killed')"
    )
    assert rows[0]["c"] == 0, f"orphan agents remain after spec-write failure: {rows}"
