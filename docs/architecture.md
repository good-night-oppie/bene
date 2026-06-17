# BENE Architecture

BENE gives each agent a private filesystem, a replayable event trail, and a model route that can be inspected from one SQLite-backed runtime.

> **Use this page to trace a request from MCP or CLI input, through agent execution, into the database you can copy, query, checkpoint, and restore.**

The architecture has three jobs: keep agent state portable, keep agent work isolated, and keep model execution understandable. The sections below follow the path an operator usually debugs: first the request flow, then the stored state, then the subsystems that move and protect it.

---

## Table of Contents

1. [Data Flow](#data-flow)
2. [System Overview](#system-overview)
3. [Runtime And Observability Boundary](#runtime-and-observability-boundary)
4. [VFS Engine](#vfs-engine)
5. [Isolation Model](#isolation-model)
6. [CCR Execution Loop](#ccr-execution-loop)
7. [Tier Router](#tier-router)
8. [MCP Server Integration](#mcp-server-integration)
9. [Design Philosophy](#design-philosophy)

---

## Data Flow

Start here when you need to answer "what happens when a client starts an agent?" The request enters through the MCP server or CLI, creates an agent in `Bene`, hands execution to the Claude Code Runner, and records every meaningful transition before returning the result.

### Complete Request Flow (MCP Client to Model)

```text
Claude Code                BENE MCP Server              BENE Core
    |                           |                           |
    |-- agent_spawn(task) ----->|                           |
    |                           |-- afs.spawn() ----------->|
    |                           |<-- agent_id --------------|
    |                           |                           |
    |                           |-- ccr.run_agent() ------->|
    |                           |                           |
    |                           |   +-- CCR Loop ----------+|
    |                           |   |                       |
    |                           |   |  Build system prompt  |
    |                           |   |  Set state            |
    |                           |   |       |               |
    |                           |   |       v               |
    |                           |   |  Tier Router          |
    |                           |   |   |                   |
    |                           |   |   | classify()        |
    |                           |   |   | select model      |
    |                           |   |   | compress context  |
    |                           |   |   |       |           |
    |                           |   |   |       v           |
    |                           |   |   |  VLLMClient       |
    |                           |   |   |  POST /v1/chat/   |
    |                           |   |   |  completions      |
    |                           |   |   |       |           |
    |                           |   |   |       v           |
    |                           |   |   |  vLLM Instance    |
    |                           |   |   |  (local GPU)      |
    |                           |   |   |       |           |
    |                           |   |   |<------+           |
    |                           |   |   |                   |
    |                           |   |  Parse response       |
    |                           |   |  Execute tool calls   |
    |                           |   |  Log to tool_calls    |
    |                           |   |  Log to events        |
    |                           |   |  Update state         |
    |                           |   |  Auto-checkpoint      |
    |                           |   |       |               |
    |                           |   |  [loop or done]       |
    |                           |   +-- End Loop -----------+
    |                           |                           |
    |                           |<-- result ----------------|
    |<-- {agent_id, result} ----|                           |
    |                           |                           |
```

That diagram is the fastest way to localize failures. If `agent_spawn` returns but the agent never changes state, inspect CCR. If CCR is active but no model response lands, inspect the Tier router and vLLM client. If the model responds but files look wrong, inspect `tool_calls`, `events`, and checkpoints for the agent.

### Data at Rest (SQLite Schema)

```text
+------------------+      +------------------+
|     agents       |      |      blobs       |
|------------------|      |------------------|
| agent_id (PK)    |      | content_hash (PK)|
| name             |      | content (BLOB)   |
| parent_id (FK)   |      | compressed       |
| status           |      | ref_count        |
| config (JSON)    |      +--------+---------+
| metadata (JSON)  |               ^
| pid              |               | content_hash
| last_heartbeat   |               |
+--------+---------+      +--------+---------+
         |                |      files       |
         | agent_id       |------------------|
         |                | file_id (PK)     |
         +--------------->| agent_id (FK)    |
         |                | path             |
         |                | content_hash (FK)|---+
         |                | version          |   |
         |                | deleted          |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|   tool_calls     |   |
         |                |------------------|   |
         |                | call_id (PK)     |   |
         |                | agent_id (FK)    |   |
         |                | tool_name        |   |
         |                | input (JSON)     |   |
         |                | output (JSON)    |   |
         |                | status           |   |
         |                | duration_ms      |   |
         |                | token_count      |   |
         |                | parent_call_id   |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|     state        |   |
         |                |------------------|   |
         |                | agent_id (FK,PK) |   |
         |                | key (PK)         |   |
         |                | value (JSON)     |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|    events        |   |
         |                |------------------|   |
         |                | event_id (PK)    |   |
         |                | agent_id (FK)    |   |
         |                | event_type       |   |
         |                | payload (JSON)   |   |
         |                | timestamp        |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|  checkpoints     |   |
                          |------------------|   |
                          | checkpoint_id(PK)|   |
                          | agent_id (FK)    |   |
                          | label            |   |
                          | event_id (FK)    |   |
                          | file_manifest    |---+
                          | state_snapshot   |
                          +------------------+
```

Every table that holds mutable agent work is scoped by `agent_id`; every file body is addressed by `content_hash`; every checkpoint points back into the same event stream. That is why one `.db` file is enough to carry the runtime.

### Concurrency Model

```text
Thread 1 (Agent A)         Thread 2 (Agent B)        Thread 3 (Agent C)
       |                          |                          |
       v                          v                          v
  thread-local conn          thread-local conn          thread-local conn
       |                          |                          |
       +----------- SQLite WAL mode (concurrent reads) -----+
       |                          |                          |
       v                          v                          v
  Write (serialized)        Read (concurrent)        Read (concurrent)
```

SQLite WAL mode permits many readers while writes serialize. BENE pairs that with one SQLite connection per thread through `threading.local()`, and the CCR semaphore caps active agent loops so parallel work does not become resource exhaustion. `busy_timeout` gives write contention up to 30000ms (30s) before surfacing an error.

---

## System Overview

BENE is the runtime boundary around agent work. External clients talk to the CLI or MCP server; agent loops use CCR and the Tier router; durable state lands in `Bene` and its SQLite-backed stores.

```text
                     External Clients
                    (Claude Code, CLI)
                           |
                           v
        +------------------------------------------+
        |           MCP Server / CLI               |
        |          (bene.mcp / bene.cli)            |
        +-----+------------------+-----------------+
              |                  |
              v                  v
     +----------------+  +----------------+
     |      CCR       |  |     Tier       |
     | Execution Loop |->|    Router      |---> vLLM Instances
     | (bene.ccr)     |  | (bene.router)  |     (httpx)
     +-------+--------+  +----------------+
             |
             v
     +------------------------------------------+
     |            BENE Core (Bene)            |
     |              (bene.core)                  |
     |                                           |
     |  +----------+ +--------+ +-------------+ |
     |  | BlobStore| | Event  | | Checkpoint  | |
     |  | (blobs)  | | Journal| | Manager     | |
     |  +----------+ +--------+ +-------------+ |
     |               |                           |
     |               v                           |
     |      +------------------+                 |
     |      |   SQLite (.db)   |                 |
     |      |   WAL mode       |                 |
     |      +------------------+                 |
     +------------------------------------------+
```

**Package:** `bene`
**CLI entry point:** `bene` (defined in `bene.cli.main:cli`)
**Configuration file:** `bene.yaml`

The core object is `Bene`, implemented in `bene/core.py`. It composes a blob store, event journal, checkpoint manager, virtual filesystem, and state store. The runner and MCP server call into that core rather than owning their own persistence.

## Runtime And Observability Boundary

BENE is the runtime. KAOS is observability around that runtime. Keep that split sharp when designing integrations or writing docs.

BENE owns execution and durable state: agent identity, VFS files, checkpoints, tool-call records, engrams, memory, skills, shared-log decisions, probes, trust, and promotion gates. Anything that changes an agent's working state should enter through BENE APIs, the CLI, or the MCP server so the SQLite runtime remains the source of truth.

KAOS observes, alerts, and nudges from outside that boundary. It may scrape tmux, summarize agent status, detect stalled sessions, watch logs, and report gaps, but it should not become a second runtime, hidden state store, or alternate promotion path. If KAOS discovers a fact that must persist, write it back through BENE memory, engrams, shared log, or a tracked issue.

The operating rule is simple:

```text
BENE = runtime, state, gates, replay
KAOS = observability, monitoring, babysitting, gap detection
```

That separation keeps BENE reproducible and KAOS replaceable. A run should still be inspectable from `bene.db` if KAOS is offline, and a KAOS alert should always point to a BENE command or record that verifies the underlying state.

---

## VFS Engine

Use the VFS engine when you need to know what an agent wrote, what version of a file it saw, or which checkpoint can recover a bad turn. It provides files, KV state, tool-call tracking, and checkpoint/restore on top of SQLite.

### SQLite Configuration

```python
conn.execute("PRAGMA journal_mode=WAL")    # Write-Ahead Logging
conn.execute("PRAGMA foreign_keys=ON")      # Referential integrity
conn.execute("PRAGMA busy_timeout=30000")   # 30s retry on lock contention
conn.execute("PRAGMA wal_autocheckpoint=100")
```

Those pragmas are the database contract: WAL for concurrent readers, foreign keys for referential integrity, and a 30s retry window for lock contention.

### Thread Safety

Each worker thread gets a separate SQLite connection. That keeps SQLite's connection rules simple while letting independent agent loops run in parallel.

```python
class Bene:
    def __init__(self, db_path: str = "bene.db", compression: str = "zstd"):
        self._local = threading.local()
        # Each thread gets its own connection via _get_conn()
```

### Content-Addressable Blob Store

`bene/blobs.py` stores file bytes by SHA-256 hash. Identical content is deduplicated across agents, `ref_count` tracks live references, `store()` compresses and saves bytes, `retrieve()` returns decompressed bytes, zstd compression runs at level 3 by default, and `gc()` removes blobs with `ref_count <= 0`.

```text
File Write Flow:

  content bytes
       |
       v
  SHA-256 hash -----> exists in blobs table?
       |                    |            |
       |                   YES           NO
       |                    |            |
       |              ref_count += 1   compress (zstd)
       |                    |            |
       |                    |        INSERT blob
       |                    |            |
       +--------------------+------------+
       |
       v
  INSERT into files table
  (agent_id, path, content_hash, size, version)
```

### Versioned File System

File writes create new versions. Replacing a path soft-deletes the previous row (`deleted = 1`) without erasing it, which keeps file history available and gives checkpoint restore something to revive. `file_history(agent_id, path)` returns the version trail. Paths are normalized with `PurePosixPath`, and parent directories are created as nested files arrive.

### Event Journal

`bene/events.py` is the append-only log for lifecycle, filesystem, state, tool, checkpoint, warning, and error events. It can be filtered by agent, `event_type`, time range, and pagination window.

| Event Type | Trigger |
|---|---|
| `agent_spawn` | Agent created |
| `agent_pause` / `agent_resume` | Lifecycle transitions |
| `agent_kill` / `agent_complete` / `agent_fail` | Terminal states |
| `file_read` / `file_write` / `file_delete` | Filesystem operations |
| `state_change` | KV state modifications |
| `tool_call_start` / `tool_call_end` | Tool execution boundaries |
| `checkpoint_create` / `checkpoint_restore` | Checkpoint operations |
| `error` / `warning` | Runtime diagnostics |

Every record has a globally ordered `event_id`, the acting `agent_id`, an event type, JSON payload, and ISO 8601 timestamp with millisecond precision.

### Checkpoint / Restore

A checkpoint captures three things in `bene/checkpoints.py`: the live file manifest `(path, content_hash, version)`, all KV state for that agent, and the event watermark at checkpoint time. Restore soft-deletes the current files, restores or un-deletes files from the manifest, and replaces the agent's state snapshot. Diffing two checkpoints reports file changes, state changes, and tool calls between their event watermarks.

---

## Isolation Model

BENE's isolation starts as a database property and can be raised to an OS property on Linux. The default is logical isolation; `bene/isolation.py` also contains the FUSE path for environments that can support mounts and cgroups.

### Tier 1 -- Logical Isolation (Default)

Logical isolation binds every VFS operation to one `agent_id`. `LogicalIsolation` wraps `Bene` so callers do not pass arbitrary agent IDs at each method call.

```python
class LogicalIsolation:
    def read(self, path: str) -> bytes:
        return self.afs.read(self.agent_id, path)  # always scoped
```

That tier has no extra runtime overhead, works on Windows, macOS, and Linux, and relies on SQL predicates such as `WHERE agent_id = ?` to keep namespaces separate.

### Tier 2 -- FUSE + Namespace Isolation (Linux Only)

When a process needs a normal filesystem view, `IsolatedAgentProcess` can mount the agent VFS at `/tmp/bene/<agent_id>`, put the process in its own Linux mount namespace with `unshare`, and optionally apply cgroups v2 controls such as `memory.max` and `cpu.weight`.

```text
Tier 2 Isolation Stack:

  +-------------------+
  | Agent Process      |
  +-------------------+
  | Mount Namespace    |  <-- unshare(CLONE_NEWNS)
  +-------------------+
  | FUSE Mount         |  <-- /tmp/bene/<agent_id>
  +-------------------+
  | Bene VFS Engine |
  +-------------------+
  | SQLite WAL         |
  +-------------------+
  | cgroups v2         |  <-- memory.max, cpu.weight
  +-------------------+
```

**Requirements:**

- Linux only (`platform.system() == "Linux"`).
- `fusepy` package — `uv sync --extra fuse` from a clone (bene is not on PyPI yet).
- Root or appropriate capabilities for namespace/cgroup operations.

### Isolation Factory

`create_isolation()` chooses the tier from configuration:

```python
isolation = create_isolation(afs, agent_id, config)
# Returns LogicalIsolation or IsolatedAgentProcess
```

---

## CCR Execution Loop

The Claude Code Runner in `bene/ccr/runner.py` is the long-running agent loop. It turns a task into a system prompt, routes model calls through Tier, executes requested tools, persists observations, and checkpoints progress.

### Loop Architecture

```text
                  +------------------+
                  |   Task (prompt)  |
                  +--------+---------+
                           |
                           v
              +------------------------+
              |  Build System Prompt   |
              |  (agent context +      |
              |   tool descriptions)   |
              +----------+-------------+
                         |
            +============+============+
            |     MAIN CCR LOOP       |
            |  (up to max_iterations) |
            |                         |
            |  +-------------------+  |
            |  |  1. PLAN          |  |
            |  |  Route via Tier   |  |
            |  |  Get model resp.  |  |
            |  +---------+---------+  |
            |            |            |
            |            v            |
            |  +-------------------+  |
            |  |  2. ACT           |  |
            |  |  Execute tool     |  |
            |  |  calls (if any)   |  |
            |  +---------+---------+  |
            |            |            |
            |            v            |
            |  +-------------------+  |
            |  |  3. OBSERVE       |  |
            |  |  Append results   |  |
            |  |  to conversation  |  |
            |  |  Check for done   |  |
            |  +---------+---------+  |
            |            |            |
            |   [not done? loop]      |
            +============+============+
                         |
                         v
                  +--------------+
                  |   Result     |
                  +--------------+
```

### Step-by-Step

1. Initialization sets the agent status to `running`, builds a system prompt from identity, tools, and task text, and stores the starting conversation in agent state.
2. Plan sends the conversation to the Tier router, which classifies the request and chooses a vLLM model.
3. Act executes any requested tool calls through `ToolRegistry`, recording `pending` -> `running` -> `success`/`error` state in `tool_calls`.
4. Observe appends tool results back into the conversation, updates iteration count and heartbeat, and stops when the model returns `end_turn` without tool calls.
5. Auto-checkpoint creates a snapshot every `checkpoint_interval` iterations; the default interval is 10.

### Termination Conditions

The loop stops on normal completion, `timeout_seconds`, `max_iterations`, a `killed` status observed between iterations, or a `paused` status that makes the loop sleep until resume.

### Parallel Execution

`ClaudeCodeRunner.run_parallel()` runs agents with `asyncio.gather()` and a semaphore. The default `max_parallel_agents` value is 8.

### Tool Registry

`bene/ccr/tools.py` owns built-in and custom tool definitions. Built-in `fs_` and `state_` tools receive the active `agent_id` automatically so their operations stay inside the caller's namespace. The table below lists the core `fs_`/`state_`/`shell` tools; `tools.py` also registers a `squirrel_localpath` helper (translates internal/Jira URLs to NFS paths) that an internal deployment may keep or de-register.

| Tool | Description |
|---|---|
| `fs_read` | Read a file from the agent's VFS |
| `fs_write` | Write content to a file |
| `fs_ls` | List directory contents |
| `fs_delete` | Delete a file |
| `fs_mkdir` | Create a directory |
| `state_get` | Read a KV state value |
| `state_set` | Write a KV state value |
| `shell_exec` | Execute a shell command (with timeout) |

Custom tools are added with `ccr.register_tool(ToolDefinition(...))`.

---

## Tier Router

The Tier router in `bene/router/tier.py` is the model-dispatch layer. It labels each inference request as `trivial`, `moderate`, `complex`, or `critical`, routes to the configured model tier, compresses context when needed, and falls back when a model call fails.

### Architecture

```text
  Incoming Request
  (messages, tools)
        |
        v
  +-------------------+
  |    Classify Task   |
  |                    |
  |  +--------------+  |
  |  | LLM-based    |  |  (preferred, uses classifier_model)
  |  | Classifier   |  |
  |  +------+-------+  |
  |         |          |
  |    [on failure]    |
  |         |          |
  |  +------v-------+  |
  |  | Heuristic    |  |  (fallback, regex + scoring)
  |  | Classifier   |  |
  |  +--------------+  |
  +--------+-----------+
           |
           v
  Classification Result
  (trivial | moderate | complex | critical)
           |
           v
  +-------------------+
  | Routing Table      |
  | trivial   -> 7B    |
  | moderate  -> 32B   |
  | complex   -> 70B   |
  | critical  -> 70B   |
  +--------+----------+
           |
           v
  +-------------------+
  | Context Compressor |
  | (if enabled)       |
  +--------+----------+
           |
           v
  +-------------------+
  |   VLLMClient      |
  |   (raw httpx)     |
  |   POST /v1/chat/  |
  |   completions     |
  +-------------------+
```

Tier is a vLLM-native cascade router. Each subsystem implements a mechanic that traces directly to a published paper — see [Research Lineage](#research-lineage) at the end of this section. Naming the design choices honestly (rather than hiding them behind a brand) lets readers swap in newer variants from the same family when they want to.

### Task Classification

`bene/router/classifier.py: LLMClassifier` sends a temperature-0 classification prompt to a small model such as `qwen2.5-coder-7b`. The desired response is one word from `trivial / moderate / complex / critical`; parsing tolerates uppercase and extra text, and errors fall back to the heuristic path. LLM classifications use fixed confidence 0.85.

This pattern — prompting a small LLM at temperature 0 to act as a classifier head whose single-token output gates dispatch — descends from RouteLLM's `causal_llm` variant ([Ong et al. 2024](https://arxiv.org/abs/2406.18665)).

`bene/router/classifier.py: HeuristicClassifier` scores the task text with three pattern sets:

- `COMPLEX_PATTERNS`: refactor, architect, security, migration, distributed, etc. (+3.0 score each)
- `MODERATE_PATTERNS`: implement, create function, write test, fix bug, etc. (+1.5 each)
- `TRIVIAL_PATTERNS`: format, rename, comment, typo, import, etc. (-1.0 each)

It also adds +2.0 for context above 50K chars, +1.0 for context above 20K chars, +1.0 for more than 10 tools (11+), and a two-tier bonus for task descriptions (+1.0 for >500 chars, +0.5 for >200 chars). Scores map to >= 5.0 critical, >= 3.0 complex, >= 1.0 moderate, otherwise trivial. Confidence is `min(0.9, 0.5 + |score| * 0.1)`.

### Routing Table

The routing table comes from each model's `use_for` list in `bene.yaml`:

```yaml
models:
  qwen2.5-coder-7b:
    use_for: [trivial, code_completion]
  qwen2.5-coder-32b:
    use_for: [moderate, code_generation]
  deepseek-r1-70b:
    use_for: [complex, critical, planning]
```

Any uncovered complexity level uses `fallback_model`. An agent-level `force_model` skips classification entirely.

The discrete-tier dispatch (rather than learning a continuous score) most closely matches AutoMix ([Aggarwal, Madaan et al. 2023](https://arxiv.org/abs/2310.12963)) and Hybrid LLM ([Ding et al. 2024](https://arxiv.org/abs/2404.14618)). Hybrid LLM is the closest mechanical ancestor of the binary version of this dispatch; Tier generalizes it from 2 tiers to 4.

### Context Compression

`ContextCompressor` in `bene/router/context.py` estimates tokens at roughly 4 characters per token, truncates long tool outputs above 2000 characters to the first 1000 plus last 500 characters with a `[truncated]` marker, drops middle messages while preserving the system message and the last 8 messages (PRESERVE_RECENT), summarizing everything in between, then trims more aggressively if the context still does not fit. It targets 85% of the selected model's `max_context`.

The "summarize the middle into a synthetic system message, preserve recent messages verbatim" pattern descends from MemGPT ([Packer et al. 2023](https://arxiv.org/abs/2310.08560)) and *Recursively Summarizing Enables Long-Term Dialogue Memory in LLMs* ([Wang et al. 2023](https://arxiv.org/abs/2308.15022)). The implementation is faithful to Anthropic's productized `/compact` mechanism (Claude API beta `compact-2026-01-12`).

### vLLM Client

`bene/router/vllm_client.py` is a small async HTTP client, not an SDK wrapper. It lazily creates an `httpx.AsyncClient`, calls `POST {base_url}/chat/completions`, sends OpenAI-compatible fields (`model`, `messages`, `temperature`, `max_tokens`, `tools`, `tool_choice`), parses raw JSON into typed dataclasses (`ChatCompletion`, `ChatChoice`, `ChatMessage`, `Usage`), and exposes `close()` for cleanup. The default timeout is 120s.

### Retry and Fallback

The router retries failed model calls up to `max_retries`; the default is 1 (a single attempt, no retry). If a non-fallback model keeps failing, later attempts switch to the configured fallback model.

### Research Lineage

| Subsystem | Closest paper | Notes |
|---|---|---|
| Cascade routing (cheap-first → escalate) | *FrugalGPT*, Chen, Zaharia, Zou (Stanford 2023) — [arXiv:2305.05176](https://arxiv.org/abs/2305.05176) | The foundational LLM-cascade paper. The tier table is FrugalGPT's "LLM cascade" pattern. |
| Difficulty-classifier-driven dispatch | *Hybrid LLM*, Ding et al. (Microsoft 2024) — [arXiv:2404.14618](https://arxiv.org/abs/2404.14618) | The closest mechanical ancestor of Tier. Tier generalizes its 2-tier router to 4 tiers. |
| LLM-as-classifier head | *RouteLLM* (`causal_llm` variant), Ong et al. (UC Berkeley + Anyscale + LMSYS, 2024) — [arXiv:2406.18665](https://arxiv.org/abs/2406.18665) | The "small LLM emits a routing label" pattern descends from this paper. |
| Multi-tier discrete cascade | *AutoMix*, Aggarwal, Madaan et al. (CMU + Google 2023) — [arXiv:2310.12963](https://arxiv.org/abs/2310.12963) | Closest precedent for the 4-bucket discretization of difficulty. |
| Rolling-summary context compression | *MemGPT*, Packer et al. (UC Berkeley 2023) — [arXiv:2310.08560](https://arxiv.org/abs/2310.08560), and *Recursively Summarizing*, Wang et al. (CAS 2023) — [arXiv:2308.15022](https://arxiv.org/abs/2308.15022) | The system-message continuation pattern. Anthropic's `/compact` is the engineering instantiation that the code targets. |

> **Note on the previous name.** This router was previously called *Tier* ("Generalized Execution Planning & Allocation"). That acronym was reverse-engineered, was not present in any of the actual ancestor papers above, and collided with the unrelated *Tier: Reflective Prompt Evolution Can Outperform Reinforcement Learning* ([Agrawal et al. 2025](https://arxiv.org/abs/2507.19457)) which is a prompt optimizer, not a router. **Tier** describes what the code mechanically does and lets readers trace the design back to its actual lineage.

---

## MCP Server Integration

The MCP server is the surface used by Claude Code and any other MCP-capable client. It exposes BENE operations while keeping implementation state in `Bene` and `ClaudeCodeRunner`.

The MCP server (`bene/mcp/server.py`) is implemented using the `mcp` Python package and supports two transport modes:

- **stdio**: For direct process integration (used by Claude Code).
- **SSE**: For HTTP-based integration via Server-Sent Events (uses Starlette + uvicorn).

The server exposes 37 tools across 9 categories (Lifecycle, VFS, Checkpoints, Query, Orchestration, Meta-Harness, Memory, Shared Log, Skills) that map directly to `Bene`, `ClaudeCodeRunner`, `MetaHarnessSearch`, and the durable coordination stores. See [mcp-integration.md](mcp-integration.md) for the complete tool reference.

### Server Initialization

```python
from bene.mcp.server import init_server

mcp_server = init_server(afs, ccr)
# afs: Bene instance
# ccr: ClaudeCodeRunner instance
```

`init_server()` sets the module-level `Bene` and `ClaudeCodeRunner` references used by all tool handlers.

---

## Design Philosophy

These constraints explain why the runtime is shaped the way it is.

### Single-file portability

Agent files, state, tool-call logs, event history, and checkpoints live in one `.db` file. Copying the runtime is a normal file copy such as `cp bene.db backup.db`, and SQLite tooling can inspect it directly.

### Zero AI SDK dependencies

BENE deliberately avoids `openai`, `litellm`, and `dspy`. vLLM traffic uses raw `httpx` requests to the OpenAI-compatible `/v1/chat/completions` endpoint, reducing dependency drift and keeping the integration surface plain.

### Isolation by default

Every filesystem operation and database query carries an `agent_id` boundary. Cross-agent data is not hidden by convention; it is absent from the API surface used by normal agent work.

### Append-only auditability

Reads, writes, deletes, state changes, tool calls, checkpoints, lifecycle changes, warnings, and errors are appended to the event journal. The result is a chronological record that can be queried after the run.

### Composition over inheritance

`Bene` owns persistence components; `ClaudeCodeRunner` delegates routing to `TierRouter`; the MCP server delegates to both. Each part can be tested or replaced without subclassing the others.
