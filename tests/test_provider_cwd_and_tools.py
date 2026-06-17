"""Tests for cwd plumbing and tool-forwarding in Claude-based providers.

Closes the regression where:
  - AgentSDKProvider silently dropped the `tools` argument and forced
    max_turns=1, making any agent that needs tool access exit on iteration 1.
  - Neither AgentSDKProvider nor ClaudeCodeProvider passed cwd= to the
    spawned Claude Code subprocess, so the child inherited the bene MCP
    server's cwd and got blocked by Claude Code's folder-trust gate.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Dict, Generator
from unittest.mock import patch, MagicMock

import pytest

from bene.router.agent_sdk import AgentSDKProvider
from bene.router.providers import ClaudeCodeProvider, create_provider


# ── AgentSDKProvider ────────────────────────────────────────────────


class _FakeResultMessage:
    """Stand-in for claude_agent_sdk.ResultMessage."""

    def __init__(self, result: str) -> None:
        self.result = result


def _install_fake_sdk(captured_options: dict) -> None:
    """Install a fake claude_agent_sdk module that records ClaudeAgentOptions."""
    fake = types.ModuleType("claude_agent_sdk")

    class FakeClaudeAgentOptions:
        def __init__(self, **kwargs):
            captured_options.update(kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

    async def fake_query(prompt, options):  # noqa: ARG001
        yield _FakeResultMessage("ok")

    # mypy: ignore attribute assignment to fake module
    fake.ClaudeAgentOptions = FakeClaudeAgentOptions  # type: ignore[attr-defined]
    fake.ResultMessage = _FakeResultMessage  # type: ignore[attr-defined]
    fake.query = fake_query  # type: ignore[attr-defined]
    sys.modules["claude_agent_sdk"] = fake


@pytest.fixture
def fake_sdk() -> Generator[Dict[str, Any], None, None]:
    captured: dict = {}
    _install_fake_sdk(captured)
    try:
        yield captured
    finally:
        sys.modules.pop("claude_agent_sdk", None)


async def test_agent_sdk_forwards_cwd(fake_sdk, tmp_path):
    """cwd= passed at init must reach ClaudeAgentOptions(cwd=...)."""
    provider = AgentSDKProvider(model_id="sonnet", cwd=str(tmp_path))
    await provider.chat(model="sonnet", messages=[{"role": "user", "content": "hi"}])
    assert fake_sdk.get("cwd") == str(tmp_path), (
        f"cwd was not forwarded to ClaudeAgentOptions; got {fake_sdk.get('cwd')!r}"
    )


async def test_agent_sdk_cwd_defaults_to_none(fake_sdk):
    """When cwd is not configured, ClaudeAgentOptions.cwd should be None
    (inheriting the parent process cwd, which is the historical behavior)."""
    provider = AgentSDKProvider(model_id="sonnet")
    await provider.chat(model="sonnet", messages=[{"role": "user", "content": "hi"}])
    assert fake_sdk.get("cwd") is None


async def test_agent_sdk_no_longer_forces_empty_tools(fake_sdk):
    """When the router passes tools, AgentSDKProvider must not drop them
    on the floor by forcing tools=[]. Today the provider does not expose tool
    use through the SDK (the SDK call is single-turn, tools are handled by
    the outer CCR loop), but the provider should at least not silently
    discard the argument."""
    provider = AgentSDKProvider(model_id="sonnet")
    fake_tools = [{"type": "function", "function": {"name": "read_file"}}]
    await provider.chat(
        model="sonnet",
        messages=[{"role": "user", "content": "hi"}],
        tools=fake_tools,
    )
    # Either the provider forwards tools to the SDK, or it surfaces them as
    # text in the prompt. The one thing it must not do is silently pass
    # tools=[] when the caller asked for tools.
    captured_tools = fake_sdk.get("tools")
    assert captured_tools != [], (
        "AgentSDKProvider passed tools=[] to ClaudeAgentOptions even though "
        "the caller supplied tools — this disables agent tool use on iteration 1."
    )


def test_agent_sdk_factory_accepts_cwd():
    """create_provider must thread cwd from config into AgentSDKProvider."""
    provider = create_provider("agent_sdk", model_id="sonnet", cwd="/tmp/x")
    assert isinstance(provider, AgentSDKProvider)
    assert provider.cwd == "/tmp/x"


# ── ClaudeCodeProvider ──────────────────────────────────────────────


async def test_claude_code_subprocess_receives_cwd(tmp_path) -> None:
    """ClaudeCodeProvider must pass cwd= to subprocess.run."""
    provider = ClaudeCodeProvider(model_id="", timeout=5.0, cwd=str(tmp_path))

    # Bypass executable resolution and capture the subprocess call.
    captured: dict = {}

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = b"hello"
    fake_result.stderr = b""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        captured["argv"] = args[0] if args else kwargs.get("args")
        return fake_result

    with patch("subprocess.run", side_effect=fake_run):
        # Force a known executable so _resolve_cmd doesn't error.
        provider._claude_exe = "/bin/echo"
        await provider.chat(model="", messages=[{"role": "user", "content": "hi"}])

    assert captured.get("cwd") == str(tmp_path), (
        f"ClaudeCodeProvider did not pass cwd=; got cwd={captured.get('cwd')!r}"
    )


def test_claude_code_factory_accepts_cwd():
    """create_provider must thread cwd from config into ClaudeCodeProvider."""
    provider = create_provider("claude_code", model_id="sonnet", cwd="/tmp/y")
    assert isinstance(provider, ClaudeCodeProvider)
    assert provider.cwd == "/tmp/y"


async def test_claude_code_cwd_defaults_to_none(tmp_path) -> None:
    """No cwd configured -> subprocess.run gets cwd=None (inherits)."""
    provider = ClaudeCodeProvider(model_id="", timeout=5.0)

    captured: dict = {}
    fake_result = MagicMock(returncode=0, stdout=b"hi", stderr=b"")

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return fake_result

    with patch("subprocess.run", side_effect=fake_run):
        provider._claude_exe = "/bin/echo"
        await provider.chat(model="", messages=[{"role": "user", "content": "hi"}])

    assert captured.get("cwd") is None
