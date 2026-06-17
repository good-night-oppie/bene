"""Claude Agent SDK provider — uses the Agent SDK for LLM calls.

Note: claude_agent_sdk.query() *does* spawn a Claude Code subprocess
(SubprocessCLITransport). The benefit over ClaudeCodeProvider is native
async streaming + structured options (system_prompt, cwd, etc.) rather
than absence of a subprocess.

Usage in bene.yaml:
    models:
      claude-sonnet:
        provider: agent_sdk
        model_id: claude-sonnet-4-6
        timeout: 120
        cwd: /mnt/iss   # optional; otherwise inherits parent process cwd
        use_for: [trivial, moderate, complex, critical]

Requires: uv pip install claude-agent-sdk
"""

from __future__ import annotations

import asyncio
import logging

from bene.router.providers import (
    LLMProvider,
    LLMResponse,
    LLMChoice,
    LLMMessage,
)

logger = logging.getLogger(__name__)


class AgentSDKProvider(LLMProvider):
    """LLM provider using the Claude Agent SDK.

    Unlike ClaudeCodeProvider (which shells out to `claude --print`),
    this uses the SDK directly:
    - Native async streaming
    - System prompt + cwd support via SDK parameters
    - Structured options instead of stdin/stdout serialization

    The SDK still spawns a Claude Code subprocess per query (the trade-off
    is structured options, not subprocess elimination).
    """

    def __init__(
        self,
        model_id: str = "claude-sonnet-4-6",
        timeout: float = 300.0,
        cwd: str | None = None,
    ):
        self.model_id = model_id
        self.timeout = timeout
        self.cwd = cwd

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        try:
            # ai-lint-override: R-II-001 - claude_agent_sdk is an optional dependency; lazy import keeps bene importable without it
            from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
        except ImportError:
            raise ImportError(
                "claude-agent-sdk not installed. Install with: uv pip install claude-agent-sdk\n"
                "Or use a different provider: claude_code, anthropic, openai, local"
            )

        # Extract system prompt and build user prompt
        system_prompt, user_prompt = self._split_messages(messages)
        if tools:
            # The SDK call is single-turn with no inner tool loop; the outer
            # CCR loop drives tool use. Surface the tool catalog in the prompt
            # so the model can at least reason about / propose calls instead
            # of silently losing tool context (the prior behavior was to
            # pass tools=[] and drop the argument).
            tool_summary = "\n".join(
                f"- {t.get('function', {}).get('name', t.get('name', '?'))}" for t in tools
            )
            user_prompt = f"{user_prompt}\n\n[Available tools]\n{tool_summary}"
        effective_model = model or self.model_id

        result_text = ""
        content_parts: list[str] = []

        max_retries = 2
        for attempt in range(max_retries):
            result_text = ""
            content_parts.clear()
            try:

                async def _run():
                    nonlocal result_text
                    async for message in query(
                        prompt=user_prompt,
                        options=ClaudeAgentOptions(
                            model=effective_model,
                            system_prompt=system_prompt or None,
                            max_turns=1,
                            permission_mode="bypassPermissions",
                            cwd=self.cwd,
                        ),
                    ):
                        if isinstance(message, ResultMessage):
                            result_text = message.result or ""
                        elif hasattr(message, "message") and hasattr(message.message, "content"):
                            for block in message.message.content or []:
                                if hasattr(block, "text") and block.text:
                                    content_parts.append(block.text)

                await asyncio.wait_for(_run(), timeout=self.timeout)
                break  # success

            except asyncio.TimeoutError:
                raise TimeoutError(f"Agent SDK call timed out after {self.timeout}s")
            except Exception as e:
                _last_error = e
                if attempt < max_retries - 1:
                    logger.warning(
                        "Agent SDK attempt %d/%d failed: %s. Retrying in 3s...",
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    await asyncio.sleep(3)
                else:
                    raise RuntimeError(f"Agent SDK error after {max_retries} attempts: {e}")

        # Use result_text if available, otherwise join content parts
        final_text = result_text or "\n".join(content_parts)

        if not final_text.strip():
            raise RuntimeError(
                "Agent SDK returned empty response. "
                "Check that ANTHROPIC_API_KEY is set or Claude Code is authenticated."
            )

        return LLMResponse(
            choices=[
                LLMChoice(
                    message=LLMMessage(role="assistant", content=final_text),
                    finish_reason="end_turn",
                )
            ],
        )

    @staticmethod
    def _split_messages(messages: list[dict]) -> tuple[str, str]:
        """Split messages into system prompt and user prompt."""
        system_parts = []
        user_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "system":
                system_parts.append(content)
            elif role == "user":
                user_parts.append(content)
            elif role == "assistant" and content:
                user_parts.append(f"[Prior assistant response]\n{content}")
            elif role == "tool" and content:
                user_parts.append(f"[Tool result]\n{content}")
        return "\n\n".join(system_parts), "\n\n".join(user_parts)

    async def close(self) -> None:
        pass
