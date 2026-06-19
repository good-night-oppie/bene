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
from bene.router.providers import ClaudeCodeProvider, CodexProvider, create_provider


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


# ── CodexProvider (GPT-5.x via the ChatGPT subscription, no API key) ─────────


def _codex_fake_run(response: str = "OK", *, write_to_file: bool = True,
                    returncode: int = 0, capture: dict | None = None):
    """A subprocess.run stand-in that writes *response* to codex's -o output file
    (and/or stdout), and records the call kwargs/argv into *capture*."""
    def fake_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args", [])
        if capture is not None:
            capture.update(kwargs)
            capture["argv"] = argv
        if write_to_file and "-o" in argv:
            with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
                f.write(response)
        r = MagicMock()
        r.returncode = returncode
        r.stdout = (b"" if write_to_file else response.encode())
        r.stderr = b""
        return r
    return fake_run


def test_codex_factory_default_is_cheapest_coding_model():
    """create_provider('codex') defaults to the cheapest ChatGPT-sub coding model —
    NOT gpt-4o (unavailable) and NOT the frontier gpt-5.5."""
    p = create_provider("codex")
    assert isinstance(p, CodexProvider)
    assert p.model_id == "gpt-5.4-mini"


def test_codex_factory_threads_model_and_cwd():
    p = create_provider("codex", model_id="gpt-5.4", cwd="/tmp/z", timeout=42.0)
    assert isinstance(p, CodexProvider)
    assert p.model_id == "gpt-5.4"
    assert p.cwd == "/tmp/z"
    assert p.timeout == 42.0


async def test_codex_chat_strips_openai_api_key_and_sets_flags(monkeypatch):
    """The subprocess must NOT inherit OPENAI_API_KEY (force the ChatGPT-sub auth, the
    task's hard 'not a pay-per-token key' requirement), and must request the read-only,
    ephemeral sandbox with the configured model."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex-must-not-leak")  # PR #68: API-key auth
    p = CodexProvider(model_id="gpt-5.4-mini", timeout=5.0, cwd="/tmp/work")
    p._codex_exe = "/bin/echo"
    cap: dict = {}
    with patch("subprocess.run", side_effect=_codex_fake_run("hi", capture=cap)):
        resp = await p.chat(model="", messages=[{"role": "user", "content": "x"}])

    assert "OPENAI_API_KEY" not in cap["env"]  # the ChatGPT-sub enforcement
    assert "CODEX_API_KEY" not in cap["env"]  # PR #68: codex exec treats it as API-key auth
    argv = cap["argv"]
    assert "--ignore-user-config" in argv  # PR #68: isolate from $CODEX_HOME/config.toml
    assert "exec" in argv and "read-only" in argv and "--ephemeral" in argv
    assert argv[argv.index("-m") + 1] == "gpt-5.4-mini"
    assert cap["cwd"] == "/tmp/work"
    assert resp.choices[0].message.content == "hi"


async def test_codex_chat_reads_output_last_message_file():
    p = CodexProvider(timeout=5.0)
    p._codex_exe = "/bin/echo"
    with patch("subprocess.run", side_effect=_codex_fake_run("def f():\n    return 1")):
        resp = await p.chat(model="", messages=[{"role": "user", "content": "write f"}])
    assert "def f()" in (resp.choices[0].message.content or "")


async def test_codex_chat_parses_tool_calls():
    out = '<tool_call id="tc_1" name="apply_patch">\n{"path": "x.py"}\n</tool_call>'
    p = CodexProvider(timeout=5.0)
    p._codex_exe = "/bin/echo"
    with patch("subprocess.run", side_effect=_codex_fake_run(out)):
        resp = await p.chat(model="", messages=[{"role": "user", "content": "patch"}])
    tcs = resp.choices[0].message.tool_calls
    assert tcs and tcs[0]["function"]["name"] == "apply_patch"


async def test_codex_chat_empty_response_raises_with_model_hint():
    p = CodexProvider(timeout=5.0)
    p._codex_exe = "/bin/echo"
    with patch("subprocess.run", side_effect=_codex_fake_run("", write_to_file=False)):
        with pytest.raises(RuntimeError, match="gpt-4o is NOT supported|empty response"):
            await p.chat(model="", messages=[{"role": "user", "content": "x"}])


def test_codex_wired_into_tier_router():
    """TierRouter builds a CodexProvider client for a provider: codex model."""
    from bene.router.tier import ModelConfig, TierRouter

    router = TierRouter(
        models={"gpt-codex": ModelConfig(
            name="gpt-codex", provider="codex", model_id="gpt-5.4-mini"
        )}
    )
    client = router.clients["gpt-codex"]
    assert isinstance(client, CodexProvider)
    assert client.model_id == "gpt-5.4-mini"


async def test_codex_config_without_model_id_uses_provider_default(tmp_path):
    """PR #68 review: a `provider: codex` config that OMITS model_id must NOT default to
    the bene.yaml key. from_config keeps model_id EMPTY, and routing passes "" to chat()
    so CodexProvider uses its own default (gpt-5.4-mini) — never `codex exec -m gpt-codex`,
    which is an invalid model."""
    import yaml

    from bene.router.tier import TierRouter

    cfgfile = tmp_path / "bene.yaml"
    cfgfile.write_text(
        yaml.safe_dump(
            {
                "models": {"gpt-codex": {"provider": "codex", "use_for": ["code_generation"]}},
                "router": {"fallback_model": "gpt-codex", "max_retries": 1},
            }
        )
    )
    router = TierRouter.from_config(str(cfgfile))
    # from_config keeps the omitted model_id EMPTY (not the key "gpt-codex")…
    assert router.models["gpt-codex"].model_id == ""
    # …and the constructed CodexProvider falls back to the cheapest coding model.
    assert router.clients["gpt-codex"].model_id == "gpt-5.4-mini"

    # routing resolves the model to "" so the provider picks its default, not the key.
    captured = {}

    class _Spy:
        async def chat(self, model, **kw):
            captured["model"] = model
            raise RuntimeError("stop after capturing the routed model")

    with pytest.raises(RuntimeError):
        await router._call_model(_Spy(), "gpt-codex", [{"role": "user", "content": "hi"}], [], {})
    assert captured["model"] == ""  # empty -> provider default, NOT "gpt-codex"


def test_codex_resolve_exe_unwraps_windows_cmd_shim(tmp_path):
    """PR #68 review: a Windows npm .CMD shim does not forward piped stdin, so the codex
    provider must resolve it to `node <cli.js>` before `codex exec -` (mirrors the Claude
    provider). A real binary is a no-op."""
    p = CodexProvider(timeout=5.0)

    # a real binary path -> no-op
    p._codex_exe = "/usr/bin/codex"
    assert p._resolve_exe() == ["/usr/bin/codex"]

    # a .CMD npm wrapper -> [node, cli.js]
    cli = tmp_path / "cli.js"
    cli.write_text("console.log('codex')")
    shim = tmp_path / "codex.CMD"
    shim.write_text('@echo off\n"%dp0%\\node.exe" "%dp0%\\cli.js" %*\n')
    p._codex_exe = str(shim)
    resolved = p._resolve_exe()
    assert len(resolved) == 2
    assert resolved[1] == str(cli)  # the cli.js the shim wraps
    assert resolved[0].endswith("node") or resolved[0].endswith("node.exe")


async def test_agent_sdk_empty_model_id_keeps_route_name():
    """PR #73 review: only CodexProvider normalizes an empty model to a default. agent_sdk
    (and claude_code) forward the model as the SDK slug, so a programmatic ModelConfig with
    no model_id must route the ROUTE NAME — not "" (which would empty ClaudeAgentOptions.model
    and break direct API users relying on the model key as the slug)."""
    from bene.router.tier import ModelConfig, TierRouter

    router = TierRouter(models={"sonnet": ModelConfig(name="sonnet", provider="agent_sdk")})

    captured = {}

    class _Spy:
        async def chat(self, model, **kw):
            captured["model"] = model
            raise RuntimeError("stop after capturing the routed model")

    with pytest.raises(RuntimeError):
        await router._call_model(_Spy(), "sonnet", [{"role": "user", "content": "hi"}], [], {})
    assert captured["model"] == "sonnet"  # route name preserved, NOT empty
