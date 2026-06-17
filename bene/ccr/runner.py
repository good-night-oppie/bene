"""Claude Code Runner — the agent execution loop.

Improvements informed by Claude Code's internal architecture (via claw-code analysis):
- Turn iteration cap (default 16) for tool-use chains within a single turn
- Per-message usage tracking for accurate token reconstruction from restored sessions
- Permission-aware tool execution (denied tools inject errors so LLM adapts)
- Continuation-style context compaction (summarize old messages, not just drop them)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from bene.ccr.prompts import build_system_prompt
from bene.ccr.tools import ToolRegistry, ToolPermissionPolicy
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.harness import LoopGuard
from bene.kernel.memory import ContextOS, GranuleStore
from bene.observe import get_observer

if TYPE_CHECKING:
    from bene.core import Bene
    from bene.observe import Observer
    from bene.router.tier import TierRouter

logger = logging.getLogger(__name__)

# Max tool-use iterations within a single turn before forcing a stop.
# Prevents runaway tool-call loops where the model keeps calling tools
# without producing a final text response.
MAX_TOOL_ITERATIONS_PER_TURN = 16


@dataclass
class ToolCall:
    """Represents a tool call from the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelResponse:
    """Represents a response from the model."""

    content: str
    tool_calls: list[ToolCall]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"
    usage: dict[str, int] | None = None
    # Surfaced for observability (langfuse cost calc keys off model + usage).
    model: str | None = None
    model_parameters: dict[str, Any] | None = None


@dataclass
class UsageTracker:
    """Tracks cumulative token usage across an agent's lifetime.

    Embeds per-turn usage in conversation messages so usage can be
    reconstructed from a restored session without external metadata.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0

    def record(self, usage: dict[str, int] | None) -> None:
        if usage:
            self.input_tokens += usage.get("prompt_tokens", 0)
            self.output_tokens += usage.get("completion_tokens", 0)
            self.total_tokens += usage.get("total_tokens", 0)
            self.turns += 1

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "turns": self.turns,
        }


class ClaudeCodeRunner:
    """
    Orchestrates agent execution loops.

    Each agent gets: a VFS namespace, a conversation, and a tool registry.
    CCR doesn't call LLMs directly — it goes through the Tier router.
    """

    def __init__(
        self,
        afs: Bene,
        router: TierRouter,
        max_iterations: int = 100,
        checkpoint_interval: int = 10,
        timeout_seconds: int = 3600,
        max_parallel_agents: int = 8,
        max_tool_iterations: int = MAX_TOOL_ITERATIONS_PER_TURN,
        permission_policy: ToolPermissionPolicy | None = None,
        context_packing_enabled: bool = False,
        context_budget_tokens: int = 32_000,
        context_strategy: str | None = None,
        context_signals: dict[str, Any] | None = None,
        context_os: ContextOS | None = None,
        loop_guard_enabled: bool = True,
        loop_guard_window: int = 20,
        loop_guard_repeat_threshold: int = 5,
        emit_engrams: bool = True,
        observer: Observer | None = None,
        observability: dict[str, Any] | None = None,
    ):
        self.afs = afs
        self.router = router
        # Pluggable observability seam: an explicit Observer wins; otherwise
        # select one from config (provider=auto → langfuse if LANGFUSE_HOST,
        # else a zero-overhead NullObserver). Never raises into construction.
        self.observer = observer if observer is not None else get_observer(observability or {})
        self.tools = ToolRegistry(afs, permission_policy=permission_policy)
        self.max_iterations = max_iterations
        self.checkpoint_interval = checkpoint_interval
        self.timeout_seconds = timeout_seconds
        self.max_parallel_agents = max_parallel_agents
        self.max_tool_iterations = max_tool_iterations
        self.context_packing_enabled = context_packing_enabled
        self.context_budget_tokens = context_budget_tokens
        self.context_strategy = context_strategy
        self.context_signals = context_signals or {}
        self.context_os = context_os or ContextOS()
        self.loop_guard_enabled = loop_guard_enabled
        self.loop_guard_window = loop_guard_window
        self.loop_guard_repeat_threshold = loop_guard_repeat_threshold
        self.emit_engrams = emit_engrams
        self._active_agents: dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_parallel_agents)

    def register_tool(self, tool) -> None:
        """Register a custom tool available to all agents."""
        self.tools.register(tool)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _context_packing_requested(self, config: dict) -> bool:
        value = config.get(
            "context_os_enabled",
            config.get(
                "context_packing_enabled",
                config.get("context_os", self.context_packing_enabled),
            ),
        )
        return self._as_bool(value)

    def _context_budget_for(self, config: dict) -> int:
        raw = config.get(
            "context_budget_tokens",
            config.get("context_budget", self.context_budget_tokens),
        )
        budget = int(raw)
        if budget < 0:
            raise ValueError("context budget must be non-negative")
        return budget

    def _context_strategy_for(self, config: dict) -> str | None:
        return config.get("context_strategy", self.context_strategy)

    def _context_signals_for(self, config: dict, items: list[dict]) -> dict[str, Any]:
        raw = config.get("context_signals", {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise TypeError("context_signals must be a dict")
        signals = {**self.context_signals, **raw}
        signals.setdefault("has_relevance", any("relevance" in item for item in items))
        return signals

    def _loop_guard_requested(self, config: dict) -> bool:
        value = config.get(
            "loop_guard_enabled",
            config.get("loop_guard", self.loop_guard_enabled),
        )
        return self._as_bool(value)

    def _new_loop_guard(self, config: dict) -> LoopGuard | None:
        if not self._loop_guard_requested(config):
            return None

        ensure_v2(self.afs.conn)
        store = EngramStore(self.afs.conn, self.afs.blobs)
        return LoopGuard(
            store,
            window=int(config.get("loop_guard_window", self.loop_guard_window)),
            repeat_threshold=int(
                config.get("loop_guard_repeat_threshold", self.loop_guard_repeat_threshold)
            ),
        )

    def _message_text(self, msg: dict[str, Any]) -> str:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        text = f"{role}: {content}"
        if msg.get("tool_calls"):
            text += "\n" + json.dumps(msg["tool_calls"], sort_keys=True, default=str)
        if msg.get("tool_call_id"):
            text += f"\ntool_call_id: {msg['tool_call_id']}"
        return text

    def _conversation_blocks(
        self,
        messages: list[dict[str, Any]],
        *,
        offset: int = 0,
    ) -> list[dict]:
        """Group assistant tool-call messages with their tool results."""
        blocks: list[dict] = []
        i = 0
        total = max(1, len(messages))
        while i < len(messages):
            start = i
            block_messages = [messages[i]]
            msg = messages[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                tool_call_ids = {
                    tc.get("id") for tc in msg.get("tool_calls", []) if isinstance(tc, dict)
                }
                i += 1
                while (
                    i < len(messages)
                    and messages[i].get("role") == "tool"
                    and messages[i].get("tool_call_id") in tool_call_ids
                ):
                    block_messages.append(messages[i])
                    i += 1
            else:
                i += 1

            end = start + len(block_messages) - 1
            global_start = offset + start
            global_end = offset + end
            role_label = "+".join(str(m.get("role", "unknown")) for m in block_messages)
            text = "\n".join(self._message_text(m) for m in block_messages)
            blocks.append(
                {
                    "id": f"msg-{global_start}-{global_end}:{role_label}",
                    "text": text,
                    "messages": block_messages,
                    "index": global_start,
                    "relevance": (end + 1) / total,
                }
            )
        return blocks

    def _record_context_manifest(
        self,
        agent_id: str,
        manifest: dict[str, Any],
    ) -> None:
        self.afs.set_state(agent_id, "context_os_manifest", manifest)
        try:
            manifests = self.afs.get_state(agent_id, "context_os_manifests")
        except KeyError:
            manifests = []
        manifests.append(manifest)
        self.afs.set_state(agent_id, "context_os_manifests", manifests)

    def _messages_for_model(
        self,
        agent_id: str,
        conversation: list[dict[str, Any]],
        config: dict,
        iteration: int,
    ) -> list[dict[str, Any]]:
        if not self._context_packing_requested(config):
            return conversation

        anchor_count = 0
        if conversation and conversation[0].get("role") == "system":
            anchor_count = 1
        if len(conversation) > anchor_count and conversation[anchor_count].get("role") == "user":
            anchor_count += 1

        anchors = conversation[:anchor_count]
        items = self._conversation_blocks(conversation[anchor_count:], offset=anchor_count)
        budget = self._context_budget_for(config)
        anchor_tokens = sum(self.context_os.estimator(self._message_text(m)) for m in anchors)
        packed_budget = max(0, budget - anchor_tokens)
        packed = self.context_os.assemble(
            items,
            packed_budget,
            signals=self._context_signals_for(config, items),
            strategy=self._context_strategy_for(config),
        )

        included = sorted(packed.included, key=lambda item: item["index"])
        model_messages = [*anchors]
        for item in included:
            model_messages.extend(item["messages"])

        anchor_ids = [f"msg-{i}:{m.get('role', 'unknown')}" for i, m in enumerate(anchors)]
        manifest = {
            "strategy": packed.strategy,
            "budget_tokens": budget,
            "packed_budget_tokens": packed_budget,
            "estimated_tokens": anchor_tokens + packed.estimated_tokens,
            "anchor_estimated_tokens": anchor_tokens,
            "packed_estimated_tokens": packed.estimated_tokens,
            "included": [*anchor_ids, *[i.get("id", i["text"][:40]) for i in included]],
            "dropped": packed.dropped,
            "source_message_count": len(conversation),
            "message_count": len(model_messages),
            "iteration": iteration,
        }
        self._record_context_manifest(agent_id, manifest)
        return model_messages

    @staticmethod
    def _observe_loop_guard(
        guard: LoopGuard | None,
        *,
        agent_id: str,
        iteration: int,
        tool_call: ToolCall,
    ):
        if guard is None:
            return None
        return guard.observe(
            {
                "agent_id": agent_id,
                "iteration": iteration,
                "tool": tool_call.name,
                "args": tool_call.input,
            }
        )

    async def run_agent(self, agent_id: str, task: str) -> str:
        """
        Main agent loop — plan, act, observe, repeat.

        Returns the agent's final output.
        """
        # Validate that at least one provider is configured
        clients = getattr(self.router, "clients", None)
        if clients is not None and not clients:
            self.afs.fail(
                agent_id,
                error="No LLM provider configured. Run 'bene setup' or add models to bene.yaml.",
            )
            raise RuntimeError(
                "No LLM provider configured. "
                "Add models to bene.yaml or run 'bene setup'. "
                "See README.md#model-providers"
            )

        agent_info = self.afs.status(agent_id)
        config = agent_info["config"]

        # Set agent to running
        self.afs.set_status(agent_id, "running", pid=os.getpid())

        # Build system prompt
        system_prompt = build_system_prompt(
            agent_id=agent_id,
            agent_name=agent_info["name"],
            tools=self.tools.list_tool_metadata(),
            task=task,
        )

        # Initialize conversation in state
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        self.afs.set_state(agent_id, "conversation", conversation)
        self.afs.set_state(agent_id, "iteration", 0)
        self.afs.set_state(agent_id, "task", task)

        start_time = time.time()
        usage_tracker = UsageTracker()
        loop_guard = self._new_loop_guard(config)
        # Engrams-by-default: every turn lands as a typed, provenance-linked trace
        # engram on the compression ladder (tier 0). Opt out with emit_engrams=False.
        granules = None
        if self.emit_engrams:
            ensure_v2(self.afs.conn)
            granules = GranuleStore(EngramStore(self.afs.conn, self.afs.blobs))

        def _emit_tool_engram(
            tool_name: str, status: str, iteration: int, error_message: str | None = None
        ) -> None:
            """Per-tool-call trace engram so `bene failure localize` can find the
            decisive failing step on a REAL run. ``steps_from_engrams`` keys on
            ``metadata.tool_name`` + ``status``/``error_message``, which the per-turn
            granule does NOT carry — without this, localize on a live run returns
            ``localized: false``. Gated by emit_engrams, same as the turn granule."""
            if granules is None:
                return
            label = f"tool:{tool_name} {status}"
            if error_message:
                label = f"{label} — {error_message[:60]}"
            granules.store.append(
                "trace",
                label[:80],
                error_message or status,
                provenance={"agent_id": agent_id},
                agent_id=agent_id,
                metadata={
                    "granule": "tool",
                    "tool_name": tool_name,
                    "status": status,
                    "error_message": error_message,
                    "iteration": iteration,
                },
            )

        # One trace per agent run; session_id groups a multi-agent workflow's
        # traces into one langfuse session (parent run, or self if root).
        session_id = agent_info.get("parent_id") or agent_id

        with self.observer.trace(
            name=f"agent:{agent_info['name']}",
            session_id=session_id,
            input={"task": task},
            metadata={"agent_id": agent_id},
        ) as trace:
            try:
                for iteration in range(self.max_iterations):
                    with trace.span(name=f"iter-{iteration}") as iter_span:
                        # Check timeout
                        elapsed = time.time() - start_time
                        if elapsed > self.timeout_seconds:
                            self.afs.fail(agent_id, error="Execution timeout")
                            raise TimeoutError(f"Agent {agent_id} timed out after {elapsed:.0f}s")

                        # Check if paused
                        current_status = self.afs.status(agent_id)["status"]
                        if current_status == "paused":
                            logger.info("Agent %s is paused, waiting...", agent_id)
                            await asyncio.sleep(1)
                            continue
                        if current_status == "killed":
                            logger.info("Agent %s was killed", agent_id)
                            return "Agent was killed"

                        model_messages = self._messages_for_model(
                            agent_id,
                            conversation,
                            config,
                            iteration,
                        )

                        # Route to appropriate model via Tier (one generation obs)
                        with iter_span.generation(
                            name="llm-call",
                            input=model_messages,
                        ) as gen:
                            response = await self.router.route(
                                agent_id=agent_id,
                                messages=model_messages,
                                tools=self.tools.list_tools(),
                                config=config,
                            )
                            gen.update(
                                output=response.content,
                                model=getattr(response, "model", None),
                                model_parameters=getattr(response, "model_parameters", None),
                                usage=response.usage,
                            )

                        # Track usage per turn
                        usage_tracker.record(response.usage)

                        # Process assistant message
                        if response.content:
                            conversation.append(
                                {
                                    "role": "assistant",
                                    "content": response.content,
                                    "usage": response.usage,
                                }
                            )

                        # Engrams-by-default: capture this turn's action as a tier-0
                        # trace engram (assistant content + any tool calls made).
                        if granules is not None:
                            tool_names = [tc.name for tc in (response.tool_calls or [])]
                            turn_text = (response.content or "").strip()
                            if tool_names:
                                turn_text = (
                                    turn_text + " → tools: " + ", ".join(tool_names)
                                ).strip()
                            granules.write_turn(
                                agent_id, turn_text or f"turn {iteration}", iteration=iteration
                            )

                        # Process tool calls
                        if response.tool_calls:
                            # Add assistant message with tool calls
                            tool_call_msg = {
                                "role": "assistant",
                                "content": response.content or "",
                                "tool_calls": [
                                    {
                                        "id": tc.id,
                                        "type": "function",
                                        "function": {
                                            "name": tc.name,
                                            "arguments": json.dumps(tc.input),
                                        },
                                    }
                                    for tc in response.tool_calls
                                ],
                            }
                            # Replace the last assistant message if we just added one
                            if response.content and conversation[-1]["role"] == "assistant":
                                conversation[-1] = tool_call_msg
                            else:
                                conversation.append(tool_call_msg)

                            for tc in response.tool_calls:
                                call_id = self.afs.log_tool_call(agent_id, tc.name, tc.input)
                                self.afs.start_tool_call(call_id)

                                with iter_span.span(
                                    name=f"tool:{tc.name}", input=tc.input
                                ) as tool_span:
                                    try:
                                        intervention = self._observe_loop_guard(
                                            loop_guard,
                                            agent_id=agent_id,
                                            iteration=iteration,
                                            tool_call=tc,
                                        )
                                        if intervention is not None:
                                            self.afs.complete_tool_call(
                                                call_id,
                                                {
                                                    "loop_guard": {
                                                        "reason": intervention.reason,
                                                        "signature": intervention.signature,
                                                        "count": intervention.count,
                                                        "message": intervention.message,
                                                        "engram_id": intervention.engram_id,
                                                    }
                                                },
                                                status="error",
                                                error_message=intervention.message,
                                            )
                                            tool_span.update(
                                                level="WARNING",
                                                status_message=intervention.message,
                                            )
                                            _emit_tool_engram(
                                                tc.name, "error", iteration, intervention.message
                                            )
                                            conversation.append(
                                                {
                                                    "role": "tool",
                                                    "content": intervention.message,
                                                    "tool_call_id": tc.id,
                                                }
                                            )
                                            continue

                                        result = await self.tools.execute(
                                            agent_id, tc.name, tc.input
                                        )
                                        result_str = (
                                            result
                                            if isinstance(result, str)
                                            else json.dumps(result)
                                        )
                                        self.afs.complete_tool_call(
                                            call_id,
                                            {"result": result_str},
                                            status="success",
                                            token_count=response.usage.get("total_tokens")
                                            if response.usage
                                            else None,
                                        )
                                        tool_span.update(output=result_str)
                                        _emit_tool_engram(tc.name, "success", iteration)
                                        conversation.append(
                                            {
                                                "role": "tool",
                                                "content": result_str,
                                                "tool_call_id": tc.id,
                                            }
                                        )
                                    except Exception as e:
                                        error_msg = f"Error: {type(e).__name__}: {e}"
                                        self.afs.complete_tool_call(
                                            call_id,
                                            {"error": str(e)},
                                            status="error",
                                            error_message=str(e),
                                        )
                                        tool_span.update(level="ERROR", status_message=str(e))
                                        _emit_tool_engram(tc.name, "error", iteration, str(e))
                                        conversation.append(
                                            {
                                                "role": "tool",
                                                "content": error_msg,
                                                "tool_call_id": tc.id,
                                            }
                                        )

                        # Check for completion
                        if response.stop_reason == "end_turn" and not response.tool_calls:
                            final_result = response.content or ""
                            self.afs.set_state(agent_id, "result", final_result)
                            self.afs.set_state(agent_id, "usage", usage_tracker.to_dict())
                            self.afs.complete(agent_id)
                            trace.update(
                                output=final_result,
                                metadata={
                                    "iterations": iteration + 1,
                                    "usage": usage_tracker.to_dict(),
                                },
                            )
                            return final_result

                        # Auto-checkpoint
                        if iteration > 0 and iteration % self.checkpoint_interval == 0:
                            self.afs.checkpoint(agent_id, label=f"auto-iter-{iteration}")
                            trace.event(name="checkpoint", attributes={"iteration": iteration})

                        # Compact conversation if it's getting large (>20 messages)
                        if len(conversation) > 20:
                            from bene.metaharness.compactor import compact_conversation

                            conversation = compact_conversation(conversation, keep_recent=6)

                        # Persist state
                        self.afs.set_state(agent_id, "iteration", iteration + 1)
                        self.afs.set_state(agent_id, "conversation", conversation)
                        self.afs.heartbeat(agent_id)

                # Hit max iterations
                self.afs.fail(agent_id, error="Max iterations reached")
                return conversation[-1].get("content", "Max iterations reached")

            except Exception as e:
                trace.update(level="ERROR", status_message=str(e))
                self.afs.fail(agent_id, error=str(e))
                raise
            finally:
                self.observer.flush()

    async def run_parallel(self, tasks: list[dict]) -> list[str]:
        """
        Spawn and run multiple agents concurrently.

        Each task dict should have:
        - name: str — agent name
        - prompt: str — the task description
        - config: dict (optional) — agent configuration
        - parent_id: str (optional) — parent agent ID
        """

        async def _run_one(task: dict) -> str:
            async with self._semaphore:
                agent_id = self.afs.spawn(
                    name=task["name"],
                    config=task.get("config", {}),
                    parent_id=task.get("parent_id"),
                )
                return await self.run_agent(agent_id, task["prompt"])

        results = await asyncio.gather(
            *[_run_one(t) for t in tasks],
            return_exceptions=True,
        )

        return [str(r) if isinstance(r, BaseException) else r for r in results]

    async def cancel_agent(self, agent_id: str) -> None:
        """Cancel a running agent."""
        task = self._active_agents.get(agent_id)
        if task and not task.done():
            task.cancel()
        self.afs.kill(agent_id)
