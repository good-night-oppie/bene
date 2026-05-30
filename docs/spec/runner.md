# bene.runner

> Agent execution engine. Orchestrates the plan-act-observe loop for one
> or more agents over a model router, with built-in tool registry,
> permission policy, usage tracking, auto-checkpointing, and conversation
> compaction.

**Reference impl**: `ionq/ccr/runner.py` `class ClaudeCodeRunner`, supporting
`ionq/ccr/tools.py` `class ToolDefinition`, `class ToolRegistry`,
`class ToolPermissionPolicy`

## Design intent

A `Runner` instance owns a model router + a tool registry. It drives agents through the standard LLM agent loop: send conversation to model → execute tool calls → append results → repeat. Per turn, it tracks usage, persists conversation+state to the agent's VFS, and auto-checkpoints at fixed intervals. Tool execution respects a `ToolPermissionPolicy` so denied tools surface as injected errors (letting the LLM adapt).

## Public surface

### `class ToolDefinition`

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., Any] | Callable[..., Awaitable[Any]]
    is_async: bool = False
    timeout_seconds: int = 60
```

**Intent**: declarative tool spec. `parameters` follows JSON Schema. `handler` is invoked with keyword arguments matched by name from the JSON Schema; bene's runner injects `agent_id` automatically for tools whose name starts with `fs_` or `state_`.

### `class ToolPermissionPolicy`

```python
@dataclass
class ToolPermissionPolicy:
    default_mode: PermissionMode = PermissionMode.ALLOW
    tool_modes: dict[str, PermissionMode]
    deny_prefixes: list[str]
```

**Methods**:
```python
authorize(tool_name: str) -> tuple[bool, str]  # (allowed, reason_if_denied)
deny_tool(name: str) -> ToolPermissionPolicy   # chainable
allow_tool(name: str) -> ToolPermissionPolicy  # chainable
```

**Intent**: tri-state policy. Resolution order: (1) `deny_prefixes` match, (2) `tool_modes` per-tool override, (3) `default_mode`. When a tool is denied, the runner raises `PermissionError` which propagates to the conversation as an injected error result.

### `class ToolRegistry`

```python
ToolRegistry(engine: Engine, *,
             permission_policy: ToolPermissionPolicy | None = None) -> ToolRegistry
register(tool: ToolDefinition) -> None
get(name: str) -> ToolDefinition | None
list_tools() -> list[dict]            # OpenAI-compatible tool spec list
list_tool_metadata() -> list[dict]    # {name, description} for prompt building
execute(agent_id: str, tool_name: str, arguments: dict) -> Any
```

**Intent**: the in-process tool registry. Built-in tools registered on construction: `fs_read`, `fs_write`, `fs_ls`, `fs_delete`, `fs_mkdir`, `state_get`, `state_set`, `shell_exec`. Implementer notes for bene below on whether to retain `shell_exec` by default.

### `class Runner`

Implementer note: the reference impl class is `ClaudeCodeRunner`. In bene this is renamed to `Runner` to avoid baking a specific LLM provider into the public surface.

```python
Runner(engine: Engine, router: Router, *,
       max_iterations: int = 100,
       checkpoint_interval: int = 10,
       timeout_seconds: int = 3600,
       max_parallel_agents: int = 8,
       max_tool_iterations: int = ...,
       permission_policy: ToolPermissionPolicy | None = None) -> Runner
```

**Intent**: construct the orchestrator. `router` is any object that implements `route(agent_id, messages, tools, config) -> ModelResponse`. Implementer must define a clear `Router` protocol — bene SHOULD NOT depend on a specific router implementation (the reference impl's `DARTRouter` is one possible adapter).

#### Tool registration

```python
register_tool(tool: ToolDefinition) -> None
```

**Intent**: forwards to the underlying `ToolRegistry`. Allows callers to add custom tools after construction.

#### Single-agent run

```python
async run_agent(agent_id: str, task: str) -> str
```

**Intent**: drive an existing agent through the plan-act-observe loop until completion, max iterations, timeout, kill, or unrecoverable error. Returns the agent's final textual output.

**Pre-conditions**:
- `agent_id` exists in the engine
- At least one provider is configured on the router

**Loop invariants** (each iteration):
1. Status is observed — if `paused`, the loop sleeps and re-checks; if `killed`, it exits.
2. Conversation is dispatched to the router.
3. Usage is recorded into the agent's usage tracker.
4. If the response carries `tool_calls`, each is logged via `Engine.log_tool_call`, started, executed via the registry, and the result appended to the conversation as a `tool` role message.
5. If `stop_reason == "end_turn"` AND no tool calls, the final text is stored as the agent's `result` state and the agent transitions to `completed`.
6. Auto-checkpoint every `checkpoint_interval` iterations.
7. Compact conversation when it grows past a threshold.
8. Persist conversation + iteration counter to state; heartbeat.

**Post-conditions** (on success):
- Agent status = `completed`
- `result` state holds the final text
- `usage` state holds cumulative `UsageTracker.to_dict()`
- All tool calls are recorded in `bene.core` tool-call tables

#### Multi-agent run

```python
async run_parallel(tasks: list[dict]) -> list[str]
```

**Intent**: spawn + run multiple agents concurrently, bounded by the registry's `max_parallel_agents` semaphore. Each `task` dict shape:
```python
{"name": str, "prompt": str, "config": dict (optional), "parent_id": str (optional)}
```

Returns final-text per task. Exceptions surface as their string form (return rather than raise) so a single failure doesn't poison the batch.

#### Cancel

```python
async cancel_agent(agent_id: str) -> None
```

**Intent**: cancel the asyncio task driving an agent + mark the agent `killed`.

### `class UsageTracker` (internal but observable via agent state)

```python
@dataclass
class UsageTracker:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    turns: int

    record(usage: dict[str, int] | None) -> None
    to_dict() -> dict
```

**Intent**: per-agent cumulative token counter. Bene's runner stores its dict form into agent state under key `usage` after completion. Per-turn usage is embedded in conversation messages so an agent reconstructed from a restored conversation has accurate cumulative usage without external metadata.

### `class ModelResponse` (router contract)

```python
@dataclass
class ModelResponse:
    content: str
    tool_calls: list[ToolCall]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"
    usage: dict[str, int] | None
```

```python
@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
```

**Intent**: the contract a router must satisfy. Bene's runner consumes any router whose `route(...)` coroutine returns a `ModelResponse`.

## Behavioral example

```python
from bene import Engine, Runner

engine = Engine("project.db")
router = MyRouter(...)   # implements .route(agent_id, messages, tools, config)
runner = Runner(engine, router, max_iterations=50)

agent_id = engine.spawn("reviewer")
result = await runner.run_agent(agent_id, "Audit auth.py for security issues.")
# result == final text from the model
# engine.status(agent_id)["status"] == "completed"
# engine.get_state(agent_id, "usage")
#   -> {"input_tokens": ..., "output_tokens": ..., "turns": ...}
```

## Implementer notes

- **Router abstraction is the boundary**. Do NOT bake a specific provider (Anthropic, OpenAI, vLLM) into `bene.runner`. Provide a `Router` protocol; let consumers supply their own adapter. Specific implementations can live in optional plugin packages.
- **Permission denial injects an error into the conversation** — the runner must catch `PermissionError` from `ToolRegistry.execute` and append it as a `tool`-role message so the LLM observes the denial and can adapt. Hidden silent denial is wrong.
- **Auto-injected args**: filesystem tools (`fs_*`) and state tools (`state_*`) get `agent_id` injected by the registry. Implementer may extend this pattern but must document any new prefix conventions in this spec page.
- **Conversation compaction** happens when the list exceeds a length threshold. Compaction must preserve the system prompt + the most recent N messages and replace earlier turns with a summary. Don't simply drop messages.
- **Tool-iteration cap per turn** prevents runaway tool-call loops where the model keeps invoking tools without producing a final text response. The reference impl uses 16; bene MAY tune this but the contract is "there must be a finite cap".
- **`shell_exec` built-in is dangerous**. The reference impl includes it; bene SHOULD make it opt-in via permission policy or omit from builtins entirely. Document the chosen default in this page when the implementation lands.
- **Async cancel must mark the agent `killed`** in addition to cancelling the task — observable status must reflect cancellation for downstream consumers.

## Cross-references

- **Depends on**: `bene.core` (agent lifecycle, tool-call tracking, state, checkpoints), `Router` protocol (external)
- **Used by**: `bene.search` (search agent is itself a runner-driven agent); `bene.proposer` (proposer agent uses runner with custom tools)
