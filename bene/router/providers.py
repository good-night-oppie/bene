# ai-lint-override: R-II-001 - Pre-existing lazy imports (shutil, re, subprocess, bene.router.agent_sdk) are intentional for optional/platform-specific paths; refactoring out of scope for this PR
# ai-lint-override: R-EH-001 - Pre-existing broad exception swallow in _find_claude fallback; refactoring out of scope for this PR
"""Provider-agnostic LLM clients.

Supports three provider types — all using raw httpx (no SDK dependencies):
  - openai:    OpenAI API, Azure OpenAI, or any OpenAI-compatible endpoint
  - anthropic: Anthropic Claude API (/v1/messages format)
  - local:     vLLM, ollama, llama.cpp, or any local /v1/chat/completions server

API keys are read from environment variables — never stored in config files.

Usage in bene.yaml:
    models:
      claude-sonnet:
        provider: anthropic
        api_key_env: ANTHROPIC_API_KEY
        model_id: claude-sonnet-4-20250514
        max_context: 200000
        use_for: [complex, critical]

      gpt-4o:
        provider: openai
        api_key_env: OPENAI_API_KEY
        model_id: gpt-4o
        max_context: 128000
        use_for: [moderate]

      local-qwen:
        provider: local
        endpoint: http://localhost:8000/v1
        max_context: 32768
        use_for: [trivial]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ── Response types (shared across providers) ─────────────────────


@dataclass
class LLMMessage:
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None


@dataclass
class LLMChoice:
    message: LLMMessage
    finish_reason: str | None = None


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class LLMResponse:
    choices: list[LLMChoice]
    usage: LLMUsage | None = None


# ── Abstract provider ────────────────────────────────────────────


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """Send a chat completion request."""

    @abstractmethod
    async def close(self) -> None:
        """Close the HTTP client."""


# ── OpenAI-compatible provider ───────────────────────────────────


class OpenAIProvider(LLMProvider):
    """OpenAI API, Azure OpenAI, or any OpenAI-compatible endpoint.

    Raw httpx — no openai SDK.
    """

    def __init__(
        self, base_url: str = "https://api.openai.com/v1", api_key: str = "", timeout: float = 120.0
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        return self._client

    async def chat(
        self, model, messages, temperature=0.1, max_tokens=4096, tools=None, tool_choice=None
    ) -> LLMResponse:
        # gpt-5.x and o1/o3 reasoning models require `max_completion_tokens`
        # and reject `max_tokens`; older models (gpt-4o, gpt-4.1, etc.)
        # accept the legacy field.
        token_field = (
            "max_completion_tokens"
            if model.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            token_field: max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        # Use per-call client to avoid stale-loop issues when the proposer and
        # evaluator's llm() helper share the same provider across asyncio contexts.
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload)
        response.raise_for_status()
        return self._parse(response.json())

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        choices = []
        for c in data.get("choices", []):
            msg = c.get("message", {})
            tool_calls = None
            if msg.get("tool_calls"):
                tool_calls = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", "{}"),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
            choices.append(
                LLMChoice(
                    message=LLMMessage(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content"),
                        tool_calls=tool_calls,
                    ),
                    finish_reason=c.get("finish_reason"),
                )
            )

        usage = None
        if data.get("usage"):
            u = data["usage"]
            usage = LLMUsage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            )
        return LLMResponse(choices=choices, usage=usage)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Anthropic provider ───────────────────────────────────────────


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API (/v1/messages format).

    Raw httpx — no anthropic SDK.
    """

    def __init__(self, api_key: str = "", timeout: float = 120.0):
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        return self._client

    async def chat(
        self, model, messages, temperature=0.1, max_tokens=4096, tools=None, tool_choice=None
    ) -> LLMResponse:
        client = await self._get_client()

        # Convert OpenAI-format messages to Anthropic format
        system_prompt = ""
        anthropic_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            elif msg.get("role") == "tool":
                # Anthropic uses tool_result content blocks
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Convert tool calls to Anthropic content blocks
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    try:
                        input_data = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        input_data = {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "input": input_data,
                        }
                    )
                anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append(
                    {
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", ""),
                    }
                )

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()
        if temperature != 0.1:
            payload["temperature"] = temperature
        if tools:
            # Convert OpenAI tool format to Anthropic
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        response = await client.post("https://api.anthropic.com/v1/messages", json=payload)
        response.raise_for_status()
        return self._parse(response.json())

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        content_text = ""
        tool_calls = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )

        finish_reason = data.get("stop_reason", "end_turn")
        if finish_reason == "tool_use":
            finish_reason = "tool_calls"

        choices = [
            LLMChoice(
                message=LLMMessage(
                    role="assistant",
                    content=content_text or None,
                    tool_calls=tool_calls or None,
                ),
                finish_reason=finish_reason,
            )
        ]

        usage = None
        if data.get("usage"):
            u = data["usage"]
            inp = u.get("input_tokens", 0)
            out = u.get("output_tokens", 0)
            usage = LLMUsage(
                input_tokens=inp,
                output_tokens=out,
                total_tokens=inp + out,
                cache_read_tokens=u.get("cache_read_input_tokens", 0),
                cache_creation_tokens=u.get("cache_creation_input_tokens", 0),
            )

        return LLMResponse(choices=choices, usage=usage)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Local provider (vLLM, ollama, llama.cpp) ─────────────────────


class LocalProvider(OpenAIProvider):
    """Local vLLM/ollama/llama.cpp — same as OpenAI format, no API key."""

    def __init__(self, endpoint: str = "http://localhost:8000/v1", timeout: float = 120.0):
        super().__init__(base_url=endpoint, api_key="", timeout=timeout)


# ── Claude Code subprocess provider ──────────────────────────────


class ClaudeCodeProvider(LLMProvider):
    """Uses the Claude Code CLI subprocess (claude --print).

    No API key needed — uses Claude Code subscription auth automatically.
    Serializes the full conversation history into each call.

    Usage in bene.yaml:
        models:
          claude-sonnet:
            provider: claude_code
            model_id: claude-sonnet-4-6   # optional, uses CC default if omitted
            max_context: 200000
            use_for: [trivial, moderate, complex, critical, code_completion, code_generation, planning]
    """

    _TOOL_CALL_RE = re.compile(
        r'<tool_call\s+id="([^"]+)"\s+name="([^"]+)">\s*(.*?)\s*</tool_call>',
        re.DOTALL,
    )

    # Fallback paths to try when 'claude' is not in PATH
    _FALLBACK_PATHS = [
        os.environ.get("CLAUDE_EXECUTABLE", ""),
        os.path.expanduser("~/.nvm/versions/node/v23.6.1/bin/claude"),
        os.path.expanduser("~/AppData/Roaming/npm/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]

    def __init__(
        self,
        model_id: str = "",
        timeout: float = 300.0,
        cwd: str | None = None,
    ):
        self.model_id = model_id
        self.timeout = timeout
        self.cwd = cwd
        # Resolve claude executable at init time
        self._claude_exe = self._find_claude()

    def _find_claude(self) -> str:
        """Find the claude executable, trying PATH and known fallback locations.

        On Windows, nvm installs both a local claude.CMD (inside the nvm bin dir)
        and a shim in the global npm bin.  The nvm-local one is preferred because
        its cli.js and node.exe are co-located and guaranteed compatible.
        """
        # 1. CLAUDE_EXECUTABLE env var (highest priority — explicit config)
        ce = os.environ.get("CLAUDE_EXECUTABLE", "")
        if ce:
            # Env var may omit the .CMD extension on Windows
            for candidate in (ce, ce + ".CMD", ce + ".cmd"):
                if os.path.isfile(candidate):
                    return candidate

        # 2. nvm-local claude.CMD (preferred over system shim)
        for nvm_path in (
            os.path.expanduser("~/.nvm/versions/node/v23.6.1/bin/claude.CMD"),
            os.path.expanduser("~/.nvm/versions/node/v23.6.1/bin/claude.cmd"),
        ):
            if os.path.isfile(nvm_path):
                return nvm_path

        # 3. PATH (may find npm global shim — less reliable on Windows)
        import shutil

        found = shutil.which("claude")
        if found:
            return found

        # 4. Remaining fallback paths
        for path in self._FALLBACK_PATHS:
            if path and os.path.isfile(path):
                return path

        return "claude"

    def _resolve_cmd(self) -> list[str]:
        """Return [executable, ...] resolving .CMD wrappers on Windows.

        On Windows, npm installs claude as a .CMD batch script that wraps
        the real Node.js call.  subprocess.run(input=...) doesn't forward
        piped stdin through CMD's & chain reliably, so we read the CMD file
        and call node + cli.js directly instead.
        """
        exe = self._claude_exe
        if not exe.upper().endswith(".CMD"):
            return [exe]
        # Parse the CMD wrapper to find node + cli.js
        try:
            cmd_dir = os.path.dirname(os.path.abspath(exe))
            with open(exe, encoding="utf-8", errors="replace") as f:
                content = f.read()
            import re as _re

            # Typical npm wrapper:  "%_prog%"  "%dp0%\node_modules\...\cli.js" %*
            # Find all quoted paths ending in .js, then resolve %dp0%
            js_paths = _re.findall(r'"([^"]+\.js)"', content)
            for js_raw in js_paths:
                # Resolve %dp0% → cmd_dir using plain string replace
                # (regex replace fails on Windows paths with backslash sequences)
                cli_js = js_raw.replace("%dp0%\\", cmd_dir + os.sep)
                cli_js = cli_js.replace("%DP0%\\", cmd_dir + os.sep)
                cli_js = cli_js.replace("%dp0%", cmd_dir)
                cli_js = os.path.normpath(cli_js)
                if os.path.isfile(cli_js):
                    # Find node executable — prefer the node that ships with the
                    # same nvm/claude installation, not the system Node.js.
                    import shutil as _shutil

                    # 1. node beside the cmd file itself
                    node_beside_cmd = os.path.join(cmd_dir, "node.exe")
                    # 2. node beside CLAUDE_EXECUTABLE (nvm bin dir)
                    _claude_env = os.environ.get("CLAUDE_EXECUTABLE", "")
                    node_beside_ce = (
                        os.path.join(os.path.dirname(_claude_env), "node.exe")
                        if _claude_env
                        else ""
                    )
                    # 3. nvm hardcoded fallback (node lives in bin/ subdir on nvm)
                    node_nvm = os.path.expanduser("~/.nvm/versions/node/v23.6.1/bin/node.exe")
                    # 4. shutil.which (may be system Node — use last)
                    node_which = _shutil.which("node") or ""
                    node_exe = next(
                        (
                            p
                            for p in (node_beside_cmd, node_beside_ce, node_nvm, node_which)
                            if p and os.path.isfile(p)
                        ),
                        "node",
                    )
                    return [node_exe, cli_js]
        except Exception:
            pass
        # Fallback: run via cmd /c (less reliable but a last resort)
        return ["cmd", "/c", exe]

    def _serialize_conversation(self, messages: list[dict], tools: list[dict] | None) -> str:
        """Flatten full conversation + tool defs into a single prompt string."""
        parts: list[str] = []

        # Preamble: tell Claude this is a structured conversation replay
        parts.append(
            "You are an autonomous research agent. The following is a structured conversation "
            "you must continue. Follow the instructions precisely.\n"
        )

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""

            if role == "system":
                parts.append(f"[SYSTEM INSTRUCTIONS]\n{content}\n[/SYSTEM INSTRUCTIONS]\n")
            elif role == "user":
                parts.append(f"[USER]\n{content}\n[/USER]\n")
            elif role == "assistant":
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        parts.append(
                            f"[ASSISTANT TOOL CALL]\n"
                            f'<tool_call id="{tc["id"]}" name="{fn["name"]}">\n'
                            f"{fn.get('arguments', '{}')}\n"
                            f"</tool_call>\n"
                            f"[/ASSISTANT TOOL CALL]\n"
                        )
                if content:
                    parts.append(f"[ASSISTANT]\n{content}\n[/ASSISTANT]\n")
            elif role == "tool":
                tool_id = msg.get("tool_call_id", "")
                parts.append(f"[TOOL RESULT id={tool_id}]\n{content}\n[/TOOL RESULT]\n")

        # Append tool definitions + format instructions
        if tools:
            tool_lines = []
            for t in tools:
                fn = t.get("function", {})
                tool_lines.append(
                    f"  - {fn.get('name', '')}: {fn.get('description', '')}\n"
                    f"    parameters: {json.dumps(fn.get('parameters', {}))}"
                )
            parts.append(
                "\n[AVAILABLE TOOLS]\n"
                + "\n".join(tool_lines)
                + "\n[/AVAILABLE TOOLS]\n"
                + "\nTo call a tool, output EXACTLY this format (preserve XML tags):\n"
                + '<tool_call id="tc_1" name="tool_name">\n'
                + '{"param": "value"}\n'
                + "</tool_call>\n"
                + "\nYou may chain multiple tool calls. Each <tool_call> block will be executed "
                + "and you will receive [TOOL RESULT] blocks in return.\n"
                + "When all tools are done and you have a final answer, output plain text with no XML tags.\n"
            )

        parts.append("\n[CONTINUE THE CONVERSATION — your response:]")
        return "\n".join(parts)

    def _parse(self, output: str) -> LLMResponse:
        """Parse claude stdout: extract tool_call blocks and plain text."""
        tool_calls: list[dict] = []
        text_segments: list[str] = []
        last_end = 0

        for m in self._TOOL_CALL_RE.finditer(output):
            pre = output[last_end : m.start()].strip()
            if pre:
                text_segments.append(pre)
            tc_id, tc_name, tc_args_raw = m.group(1), m.group(2), m.group(3).strip()
            try:
                args_str = json.dumps(json.loads(tc_args_raw))
            except json.JSONDecodeError:
                args_str = json.dumps({"raw": tc_args_raw})
            tool_calls.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": tc_name, "arguments": args_str},
                }
            )
            last_end = m.end()

        tail = output[last_end:].strip()
        if tail:
            text_segments.append(tail)

        final_text = "\n".join(text_segments) or None
        stop_reason = "tool_calls" if tool_calls else "end_turn"

        return LLMResponse(
            choices=[
                LLMChoice(
                    message=LLMMessage(
                        role="assistant",
                        content=final_text,
                        tool_calls=tool_calls or None,
                    ),
                    finish_reason=stop_reason,
                )
            ],
        )

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        import subprocess

        prompt = self._serialize_conversation(messages, tools)
        prompt_bytes = prompt.encode("utf-8")

        cmd = self._resolve_cmd() + ["--print"]
        effective_model = model or self.model_id
        if effective_model:
            cmd += ["--model", effective_model]

        # Strip CLAUDECODE so nested claude --print doesn't refuse to start.
        # Also strip Anthropic BYOK env vars so the subprocess falls back to
        # the OAuth / claude.ai subscription path rather than a potentially
        # depleted raw API key.
        _STRIP = {"CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"}
        env = {k: v for k, v in os.environ.items() if k not in _STRIP}
        timeout = self.timeout
        cwd = self.cwd

        def _run_sync() -> subprocess.CompletedProcess:
            return subprocess.run(
                cmd,
                input=prompt_bytes,
                capture_output=True,
                env=env,
                timeout=timeout,
                cwd=cwd,
            )

        loop = asyncio.get_running_loop()

        # Retry with backoff on empty responses (rate limiting)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                proc_result = await loop.run_in_executor(None, _run_sync)
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"claude subprocess timed out after {timeout}s")

            if proc_result.returncode != 0:
                err = proc_result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"claude --print failed (rc={proc_result.returncode}): {err}")

            stdout_text = proc_result.stdout.decode("utf-8", errors="replace")
            proc_result.stderr.decode("utf-8", errors="replace").strip()

            if stdout_text.strip():
                return self._parse(stdout_text)

            # Empty response — likely rate limited by active Claude Code session
            if attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "claude --print returned empty (attempt %d/%d, retrying in %ds). "
                    "This usually means an active Claude Code session is consuming the API quota.",
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                raise RuntimeError(
                    "claude --print returned empty response after 3 attempts. "
                    "This happens when an active Claude Code session is consuming "
                    "the API quota. Either close the active session first, or use "
                    "provider: anthropic with an ANTHROPIC_API_KEY for independent quota."
                )

        # unreachable but keeps type checker happy
        raise RuntimeError("claude --print failed")

    async def close(self) -> None:
        pass  # No persistent connections


# ── Codex / ChatGPT-subscription subprocess provider ─────────────


class CodexProvider(LLMProvider):
    """GPT-5.x via the `codex` CLI on a ChatGPT Pro/Plus subscription — NO API key.

    Shells out to `codex exec` (non-interactive), which authenticates through
    ``~/.codex/auth.json`` (the ChatGPT OAuth tokens, ``auth_mode=chatgpt``) — NOT a
    pay-per-token OpenAI API key. Mirrors :class:`ClaudeCodeProvider` (which shells
    ``claude --print`` on the Claude subscription). This is the **meta-harness
    executor**: the model that writes/applies harness mutations for OHE + SECH.

    The model is set with ``-m``; the call runs in a **read-only, ephemeral** sandbox
    so a ``.chat()`` has no filesystem side effects — the model RETURNS the code/text
    and the caller (the Refiner / Contract-S apply) is what writes it.

    IMPORTANT — model availability (from ``~/.codex/models_cache.json`` for this
    account): the ChatGPT account exposes exactly these via codex —
      - ``gpt-5.5``              frontier (complex coding/research)
      - ``gpt-5.4``             strong everyday coding
      - ``gpt-5.4-mini``        small, cost-efficient (DEFAULT — cheapest coding model)
      - ``gpt-5.3-codex-spark`` ultra-fast coding
    **'gpt-4o' is NOT available** (codex rejects it: "The 'gpt-4o' model is not
    supported when using Codex with a ChatGPT account"; so are gpt-5-codex / o4-mini /
    the gpt-5-mini line). Per the "don't use the latest frontier, use the cheapest
    coding model" directive, the default is ``gpt-5.4-mini``. Override via ``model_id``.

    Usage in bene.yaml:
        models:
          gpt-codex:
            provider: codex
            model_id: gpt-5.4-mini   # cheapest ChatGPT-sub coding model; NOT gpt-4o
            max_context: 200000
            use_for: [code_generation]
    """

    # Same tool-call tag contract the ClaudeCodeProvider prompt uses, so this is a
    # drop-in for the TierRouter interface. (Serialization mirrors ClaudeCodeProvider;
    # a shared helper is a sensible follow-up refactor.)
    _TOOL_CALL_RE = re.compile(
        r'<tool_call\s+id="([^"]+)"\s+name="([^"]+)">\s*(.*?)\s*</tool_call>',
        re.DOTALL,
    )
    # Cheapest coding model on the ChatGPT sub (gpt-4o is rejected; gpt-5.5 is frontier).
    _DEFAULT_MODEL = "gpt-5.4-mini"
    _FALLBACK_PATHS = [
        os.environ.get("CODEX_EXECUTABLE", ""),
        os.path.expanduser("~/.local/bin/codex"),
        "/usr/local/bin/codex",
        "/opt/homebrew/bin/codex",
    ]

    def __init__(self, model_id: str = "", timeout: float = 300.0, cwd: str | None = None):
        self.model_id = model_id or self._DEFAULT_MODEL
        self.timeout = timeout
        self.cwd = cwd
        self._codex_exe = self._find_codex()

    def _find_codex(self) -> str:
        ce = os.environ.get("CODEX_EXECUTABLE", "")
        if ce and os.path.isfile(ce):
            return ce
        import shutil

        found = shutil.which("codex")
        if found:
            return found
        for path in self._FALLBACK_PATHS:
            if path and os.path.isfile(path):
                return path
        return "codex"

    def _serialize_conversation(self, messages: list[dict], tools: list[dict] | None) -> str:
        """Flatten the conversation + tool defs into a single codex prompt string."""
        parts: list[str] = [
            "You are an autonomous coding executor. Continue the following structured "
            "conversation precisely. Output only your response.\n"
        ]
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "system":
                parts.append(f"[SYSTEM INSTRUCTIONS]\n{content}\n[/SYSTEM INSTRUCTIONS]\n")
            elif role == "user":
                parts.append(f"[USER]\n{content}\n[/USER]\n")
            elif role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    parts.append(
                        f'[ASSISTANT TOOL CALL]\n<tool_call id="{tc["id"]}" '
                        f'name="{fn["name"]}">\n{fn.get("arguments", "{}")}\n</tool_call>\n'
                    )
                if content:
                    parts.append(f"[ASSISTANT]\n{content}\n[/ASSISTANT]\n")
            elif role == "tool":
                parts.append(
                    f"[TOOL RESULT id={msg.get('tool_call_id', '')}]\n{content}\n[/TOOL RESULT]\n"
                )
        if tools:
            tool_lines = [
                f"  - {t.get('function', {}).get('name', '')}: "
                f"{t.get('function', {}).get('description', '')}\n"
                f"    parameters: {json.dumps(t.get('function', {}).get('parameters', {}))}"
                for t in tools
            ]
            parts.append(
                "\n[AVAILABLE TOOLS]\n" + "\n".join(tool_lines) + "\n[/AVAILABLE TOOLS]\n"
                '\nTo call a tool, output EXACTLY:\n<tool_call id="tc_1" name="tool_name">\n'
                '{"param": "value"}\n</tool_call>\n'
                "When done with a final answer, output plain text with no XML tags.\n"
            )
        parts.append("\n[CONTINUE — your response:]")
        return "\n".join(parts)

    def _parse(self, output: str) -> LLMResponse:
        """Parse codex output-last-message: tool_call blocks + plain text."""
        tool_calls: list[dict] = []
        text_segments: list[str] = []
        last_end = 0
        for m in self._TOOL_CALL_RE.finditer(output):
            pre = output[last_end : m.start()].strip()
            if pre:
                text_segments.append(pre)
            tc_id, tc_name, tc_args_raw = m.group(1), m.group(2), m.group(3).strip()
            try:
                args_str = json.dumps(json.loads(tc_args_raw))
            except json.JSONDecodeError:
                args_str = json.dumps({"raw": tc_args_raw})
            tool_calls.append(
                {"id": tc_id, "type": "function",
                 "function": {"name": tc_name, "arguments": args_str}}
            )
            last_end = m.end()
        tail = output[last_end:].strip()
        if tail:
            text_segments.append(tail)
        final_text = "\n".join(text_segments) or None
        return LLMResponse(
            choices=[
                LLMChoice(
                    message=LLMMessage(
                        role="assistant",
                        content=final_text,
                        tool_calls=tool_calls or None,
                    ),
                    finish_reason="tool_calls" if tool_calls else "end_turn",
                )
            ],
        )

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        import subprocess
        import tempfile

        prompt_bytes = self._serialize_conversation(messages, tools).encode("utf-8")
        effective_model = model or self.model_id

        # Capture the final assistant message via -o (a file) so we get a clean
        # completion, not the noisy stderr (MCP/skill load warnings) or --json JSONL.
        out_fd, out_path = tempfile.mkstemp(prefix="codex-out-", suffix=".txt")
        os.close(out_fd)
        cmd = [
            self._codex_exe, "exec",
            "--skip-git-repo-check", "--ephemeral",
            "-s", "read-only", "--color", "never",
            "-o", out_path,
        ]
        if effective_model:
            cmd += ["-m", effective_model]
        cmd += ["-"]  # read the prompt from stdin

        # Force the ChatGPT-subscription auth path: strip any OPENAI_API_KEY so codex
        # never falls back to a pay-per-token key (the task's hard requirement).
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}

        def _run_sync() -> subprocess.CompletedProcess:
            return subprocess.run(
                cmd, input=prompt_bytes, capture_output=True,
                env=env, timeout=self.timeout, cwd=self.cwd,
            )

        loop = asyncio.get_running_loop()
        try:
            proc = await loop.run_in_executor(None, _run_sync)
        except subprocess.TimeoutExpired as exc:
            try:
                os.unlink(out_path)
            except OSError:
                pass
            raise TimeoutError(f"codex exec timed out after {self.timeout}s") from exc

        try:
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace").strip()[-800:]
                raise RuntimeError(f"codex exec failed (rc={proc.returncode}): {err}")
            try:
                with open(out_path, encoding="utf-8", errors="replace") as f:
                    final_message = f.read().strip()
            except OSError:
                final_message = ""
            if not final_message:
                # Fall back to stdout if the output file is empty.
                final_message = proc.stdout.decode("utf-8", errors="replace").strip()
            if not final_message:
                tail = proc.stderr.decode("utf-8", errors="replace").strip()[-400:]
                raise RuntimeError(
                    f"codex exec returned an empty response (model={effective_model!r}). "
                    "Note: gpt-4o is NOT supported on a ChatGPT account — supported slugs: "
                    f"gpt-5.5 / gpt-5.4 / gpt-5.4-mini / gpt-5.3-codex-spark. {tail}"
                )
            return self._parse(final_message)
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    async def close(self) -> None:
        pass  # no persistent connections


# ── Factory ──────────────────────────────────────────────────────


def create_provider(provider_type: str, **kwargs) -> LLMProvider:
    """Create an LLM provider from config.

    Args:
        provider_type: "openai", "anthropic", or "local"
        **kwargs: Provider-specific config (api_key, endpoint, etc.)
    """
    if provider_type == "anthropic":
        api_key = kwargs.get("api_key") or os.environ.get(
            kwargs.get("api_key_env", "ANTHROPIC_API_KEY"), ""
        )
        if not api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or add api_key_env to your model config."
            )
        return AnthropicProvider(api_key=api_key, timeout=kwargs.get("timeout", 120.0))

    elif provider_type == "openai":
        api_key = kwargs.get("api_key") or os.environ.get(
            kwargs.get("api_key_env", "OPENAI_API_KEY"), ""
        )
        if not api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                "or add api_key_env to your model config."
            )
        base_url = kwargs.get("endpoint") or "https://api.openai.com/v1"
        return OpenAIProvider(
            base_url=base_url, api_key=api_key, timeout=kwargs.get("timeout", 120.0)
        )

    elif provider_type == "local":
        endpoint = kwargs.get("endpoint") or "http://localhost:8000/v1"
        return LocalProvider(endpoint=endpoint, timeout=kwargs.get("timeout", 120.0))

    elif provider_type == "claude_code":
        model_id = kwargs.get("model_id", "")
        timeout = kwargs.get("timeout", 120.0)
        cwd = kwargs.get("cwd")
        return ClaudeCodeProvider(model_id=model_id, timeout=timeout, cwd=cwd)

    elif provider_type == "agent_sdk":
        from bene.router.agent_sdk import AgentSDKProvider

        model_id = kwargs.get("model_id", "sonnet")
        timeout = kwargs.get("timeout", 300.0)
        cwd = kwargs.get("cwd")
        return AgentSDKProvider(model_id=model_id, timeout=timeout, cwd=cwd)

    elif provider_type == "codex":
        # GPT-5.x via the codex CLI on a ChatGPT subscription (no API key).
        return CodexProvider(
            model_id=kwargs.get("model_id", ""),
            timeout=kwargs.get("timeout", 300.0),
            cwd=kwargs.get("cwd"),
        )

    else:
        raise ValueError(
            f"Unknown provider: {provider_type}. "
            "Use 'openai', 'anthropic', 'local', 'claude_code', 'agent_sdk', or 'codex'."
        )
