# BENE as an MCP Server

<a id="overview"></a>

Hook BENE up to Claude Code once, and from then on you run agents in plain English — spawn one to write tests, checkpoint it before a risky change, roll it back when the change goes wrong, and query everything it did, without leaving the conversation.

> **One entry in `settings.json` gives Claude Code 37 BENE tools — agents, files, checkpoints, SQL, meta-harness search, memory, shared log, and skills — all backed by a single local SQLite file.**

Everything these tools touch lives in `bene.db` on your machine. The stdio transport opens no network socket, and `agent_query` is read-only by construction — write statements raise a `PermissionError`. Network access only happens if you ask for it, by starting the SSE transport on a host you choose.


On this page:

- [Connect Claude Code](#connect-claude-code)
- [Run the server directly](#run-the-server-directly)
- [The cheaper path: the `--json` CLI](#the-cheaper-path-the---json-cli)
- [Tool reference](#tool-reference)
- [Conversations that work today](#conversations-that-work-today)
- [What the CLI-first path adds](#what-the-cli-first-path-adds)

Original anchor map: [Overview](#overview), [CLI Alternative](#cli-alternative), [Starting the MCP Server](#starting-the-mcp-server), [Claude Code Integration](#claude-code-integration), [Available Tools](#available-tools), [Example Conversation Flows](#example-conversation-flows).

Under the hood: the server lives in `bene/mcp/server.py`, built on the `mcp` Python package. It wraps one `Bene` instance plus a `ClaudeCodeRunner` and publishes 37 tools spanning 9 categories — Lifecycle, VFS, Checkpoints, Query, Orchestration, Meta-Harness, Memory, Shared Log, and Skills. Any [Model Context Protocol](https://modelcontextprotocol.io/) client gets the same surface.

---

<a id="claude-code-integration"></a>

## Connect Claude Code

### Register the server

Drop this into `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "bene": {
      "command": "bene",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

### Point at a specific database and config

```json
{
  "mcpServers": {
    "bene": {
      "command": "bene",
      "args": [
        "serve",
        "--transport", "stdio",
        "--db", "/path/to/project/bene.db",
        "--config-file", "/path/to/project/bene.yaml"
      ]
    }
  }
}
```

### Run from a source checkout with uv

No global install? Have `uv run` launch it straight from the source tree:

```json
{
  "mcpServers": {
    "bene": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/bene",
        "bene", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

### Check it worked

Restart Claude Code after editing settings, then ask:

> "What BENE tools are available?"

All 37 should come back in the answer.

---

<a id="starting-the-mcp-server"></a>

## Run the server directly

Two transports exist. With **stdio**, the MCP client launches `bene serve` as a child process and talks over stdin/stdout — the right choice for Claude Code. With **SSE**, a Starlette/uvicorn HTTP server speaks Server-Sent Events, for clients that reach BENE over the network.

### stdio (the default)

```bash
bene serve --transport stdio
```

MCP messages arrive on stdin; responses leave on stdout; Claude Code owns the process from launch to exit.

**Options:**

```bash
bene serve \
  --transport stdio \
  --db ./bene.db \
  --config-file ./bene.yaml
```

### SSE (network access)

```bash
bene serve --transport sse --host 127.0.0.1 --port 3100
```

The HTTP server exposes two routes:

- `GET /sse` — where MCP clients open the event stream.
- `POST /messages` — where MCP clients post their messages.

**Options:**

```bash
bene serve \
  --transport sse \
  --host 0.0.0.0 \
  --port 3100 \
  --db ./bene.db \
  --config-file ./bene.yaml
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BENE_DB` | `./bene.db` | Database file path (overridden by `--db`). |
| `BENE_CONFIG` | `./bene.yaml` | Configuration file path (overridden by `--config-file`). |

### No `bene.yaml`? Still works

When no `bene.yaml` is present, the server falls back to the `claude_code` provider (claude-sonnet-4-6). File management, checkpoints, and queries all keep working in that state — none of them touch a model, so no vLLM setup is required.

---

<a id="cli-alternative"></a>

## The cheaper path: the `--json` CLI

Every BENE command accepts `--json`. That means any agent that can run a shell command can drive BENE with structured output — no MCP client, no schema injection:

```bash
# Structured JSON output — any agent can parse this
bene --json ls
bene --json status <agent-id>
bene --json query "SELECT * FROM agents WHERE status='running'"
bene --json mh status <search-agent-id>

# Background worker — survives parent exit
bene mh search -b text_classify -n 10 --background
```

Reach for the CLI rather than MCP when:

- token budget matters — shelling out skips the MCP schema overhead entirely
- a long search must outlive process restarts
- your agent framework doesn't speak MCP

---

<a id="available-tools"></a>

## Tool reference

The 37 tools, grouped by what you're trying to do. The detailed tables below cover the primary workflow tools; the addendum lists the extra memory, shared-log, skill, and stepwise meta-harness tools exposed by the same server.

### Start and steer agents

#### agent_spawn

Create an agent in its own virtual filesystem and hand it a task, in one call.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name for the agent. |
| `task` | string | yes | Task description for the agent to execute. |
| `config` | object | no | Agent configuration (model, temperature, etc.). Default: `{}`. |

**Returns:** `agent_id` and `result`, as JSON.

**Example:**

```json
{
  "name": "test-writer",
  "task": "Write unit tests for the authentication module",
  "config": {"force_model": "deepseek-r1-70b"}
}
```

**Response:**

```json
{
  "agent_id": "01HXY...",
  "result": "I've written 12 unit tests covering..."
}
```

#### agent_spawn_only

Create the agent but hold off on execution — the way to go when you want to seed its VFS first.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name for the agent. |
| `config` | object | no | Agent configuration. Default: `{}`. |

**Returns:** `agent_id` and `status`, as JSON.

**Example:**

```json
{
  "name": "code-analyzer"
}
```

**Response:**

```json
{
  "agent_id": "01HXY...",
  "status": "initialized"
}
```

#### agent_parallel

Fan out several agents at once and collect every result.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `tasks` | array | yes | Array of task objects, each with `name` (string, required), `prompt` (string, required), and `config` (object, optional). |

**Returns:** a JSON array of indexed results.

**Example:**

```json
{
  "tasks": [
    {"name": "test-writer", "prompt": "Write unit tests for payments"},
    {"name": "doc-writer", "prompt": "Update payment API documentation"},
    {"name": "refactorer", "prompt": "Refactor payments to use Stripe v3", "config": {"force_model": "deepseek-r1-70b"}}
  ]
}
```

**Response:**

```json
[
  {"index": 0, "result": "I've written 8 test cases covering..."},
  {"index": 1, "result": "Updated the API docs with..."},
  {"index": 2, "result": "Refactored the payments module to..."}
]
```

#### agent_status

Inspect one agent — or omit the ID and list them all.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | no | Agent ID. Omit to list all agents. |
| `status_filter` | string | no | Filter by status (`running`, `completed`, `failed`, etc.). |

**Returns:** one JSON object for a single agent; a JSON array when listing.

**Example — one agent:**

```json
{
  "agent_id": "01HXY..."
}
```

**Response:**

```json
{
  "agent_id": "01HXY...",
  "name": "test-writer",
  "parent_id": null,
  "created_at": "2026-03-30T10:00:00.000",
  "status": "completed",
  "config": {"force_model": "deepseek-r1-70b"},
  "metadata": {},
  "pid": 12345,
  "last_heartbeat": "2026-03-30T10:05:00.000"
}
```

**Example — every running agent:**

```json
{
  "status_filter": "running"
}
```

#### agent_pause

Suspend a running agent; `agent_resume` picks it back up later.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID to pause. |

**Returns:** a confirmation.

#### agent_resume

Continue an agent that was paused.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID to resume. |

**Returns:** a confirmation.

#### agent_kill

Stop a running agent immediately.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID to kill. |

**Returns:** a confirmation.

**Example:**

```json
{
  "agent_id": "01HXY..."
}
```

**Response:**

```text
Agent 01HXY... killed
```

### Move files in and out

#### agent_read

Fetch one file out of an agent's VFS.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `path` | string | yes | File path to read. |

**Returns:** the file body, as UTF-8 text.

**Example:**

```json
{
  "agent_id": "01HXY...",
  "path": "/src/auth.py"
}
```

#### agent_write

Put a file into an agent's VFS.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `path` | string | yes | File path. |
| `content` | string | yes | File content. |

**Returns:** a confirmation including the byte count.

**Example:**

```json
{
  "agent_id": "01HXY...",
  "path": "/src/auth.py",
  "content": "def authenticate(user, password):\n    ..."
}
```

**Response:**

```text
Written 41 bytes to 01HXY...:/src/auth.py
```

#### agent_ls

Enumerate a directory inside an agent's VFS.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `path` | string | no | Directory path. Default: `/`. |

**Returns:** a JSON array; every entry carries path, name, is_dir, size, modified_at, and version.

**Example:**

```json
{
  "agent_id": "01HXY...",
  "path": "/src"
}
```

**Response:**

```json
[
  {"path": "/src/auth.py", "name": "auth.py", "is_dir": false, "size": 1234, "modified_at": "2026-03-30T10:00:00.000", "version": 2},
  {"path": "/src/utils", "name": "utils", "is_dir": true, "size": 0, "modified_at": "2026-03-30T09:55:00.000", "version": 1}
]
```

### Snapshot and roll back

#### agent_checkpoint

Snapshot the agent's files and KV store exactly as they stand.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `label` | string | no | Optional label for the checkpoint. |

**Returns:** a confirmation carrying the new checkpoint ID.

**Example:**

```json
{
  "agent_id": "01HXY...",
  "label": "pre-refactor"
}
```

**Response:**

```text
Checkpoint 01HABC... created for agent 01HXY...
```

#### agent_checkpoints

Enumerate every checkpoint an agent has taken.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |

**Returns:** a JSON array; each checkpoint carries `checkpoint_id`, `label`, `created_at`, `event_id`, and `metadata`.

**Example:**

```json
{"agent_id": "01HXY..."}
```

**Response:**

```json
[
  {"checkpoint_id": "01HABC...", "label": "pre-refactor", "created_at": "2026-03-31T10:00:00.000", "event_id": 42, "metadata": {}},
  {"checkpoint_id": "01HDEF...", "label": "post-refactor", "created_at": "2026-03-31T10:15:00.000", "event_id": 87, "metadata": {}}
]
```

#### agent_restore

Rewind an agent to a checkpoint you took earlier.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `checkpoint_id` | string | yes | Checkpoint ID to restore. |

**Returns:** a confirmation.

**Example:**

```json
{
  "agent_id": "01HXY...",
  "checkpoint_id": "01HABC..."
}
```

**Response:**

```text
Agent 01HXY... restored to checkpoint 01HABC...
```

#### agent_diff

See what moved between two checkpoints — files, state keys, and the tool calls in between.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `from_checkpoint` | string | yes | Source checkpoint ID. |
| `to_checkpoint` | string | yes | Target checkpoint ID. |

**Returns:** JSON covering file changes, state changes, and the tool calls between the two snapshots.

**Example:**

```json
{
  "agent_id": "01HXY...",
  "from_checkpoint": "01HABC...",
  "to_checkpoint": "01HDEF..."
}
```

**Response:**

```json
{
  "files": {
    "added": ["/src/new_module.py"],
    "removed": [],
    "modified": ["/src/auth.py"]
  },
  "state": {
    "added": {"new_key": "value"},
    "removed": {},
    "modified": {"iteration": {"from": 5, "to": 15}}
  },
  "tool_calls": [
    {"call_id": "...", "tool_name": "fs_write", "status": "success", "duration_ms": 12, "token_count": 500}
  ]
}
```

### Ask the database

#### agent_query

Read-only SQL straight against `bene.db`.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `sql` | string | yes | SQL SELECT query. |

**Returns:** result rows as a JSON array.

**Example:**

```json
{
  "sql": "SELECT name, status, created_at FROM agents ORDER BY created_at DESC LIMIT 5"
}
```

**Response:**

```json
[
  {"name": "test-writer", "status": "completed", "created_at": "2026-03-30T10:00:00.000"},
  {"name": "refactorer", "status": "running", "created_at": "2026-03-30T09:55:00.000"}
]
```

**Note:** SELECT is the only statement type accepted. INSERT, UPDATE, DELETE, DROP, ALTER, and CREATE all come back as a `PermissionError`.

### Breed better harnesses

#### mh_search

Kick off a Meta-Harness search: seed harnesses get scored on a benchmark, then each iteration proposes and evaluates improvements drawn from full execution traces.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `benchmark` | string | yes | Benchmark name: `text_classify`, `math_rag`, `agentic_coding`, or a custom registered benchmark. |
| `max_iterations` | integer | no | Number of search iterations. Default: 10. |
| `candidates_per_iteration` | integer | no | Candidates proposed per iteration. Default: 2. |
| `config` | object | no | Additional SearchConfig overrides. |

**Returns:** JSON carrying `status`, `pid`, `log_path`, and `message`.

**Example:**

```json
{"benchmark": "text_classify", "max_iterations": 10, "candidates_per_iteration": 2}
```

#### mh_frontier

Pull the Pareto frontier once a search has finished.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `search_agent_id` | string | yes | Search agent ID returned by `mh_search`. |

**Returns:** the Pareto frontier as JSON — harness IDs, scores, iterations.

#### mh_resume

Pick an interrupted search back up at its last finished iteration. Nothing is lost: prior harness evaluations, traces, and frontier state carry over, and the benchmark, candidate count, and objectives stay exactly as configured.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `search_agent_id` | string | yes | Search agent ID of the interrupted search. |
| `benchmark` | string | yes | Benchmark the search was started on (`text_classify`, `math_rag`, or `agentic_coding`) — the worker needs it to resume scoring. |

**Returns:** JSON carrying `search_agent_id`, `status`, `pid`, `log_path`, and `message`.

**Example:**

```json
{
  "search_agent_id": "01HXY...",
  "benchmark": "text_classify"
}
```

**Response:**

```json
{
  "search_agent_id": "01HXY...",
  "status": "resuming",
  "pid": 12345,
  "log_path": "/path/to/bene-worker-12345.log",
  "message": "Resume worker launched (PID 12345). Log: /path/to/bene-worker-12345.log."
}
```

### Additional tools exposed by the same server

The MCP list currently includes these 19 additional tools beyond the detailed workflow tables above:

- Meta-Harness step tools: `mh_start_search`, `mh_submit_candidate`, `mh_next_iteration`, `mh_write_skill`, `mh_spawn_coevolution`, `mh_hub_sync`
- Agent memory: `agent_memory_write`, `agent_memory_search`, `agent_memory_read`
- Shared log: `shared_log_intent`, `shared_log_vote`, `shared_log_decide`, `shared_log_append`, `shared_log_read`
- Skills: `skill_save`, `skill_search`, `skill_apply`, `skill_list`, `skill_outcome`

Verify the current surface from the source checkout:

```bash
uv run python - <<'PY'
import asyncio
from bene.mcp.server import list_tools
async def main():
    tools = await list_tools()
    print(len(tools))
    print("\n".join(t.name for t in tools))
asyncio.run(main())
PY
```

---

<a id="example-conversation-flows"></a>

## Conversations that work today

Nine end-to-end exchanges, ordered the way work usually unfolds: build, fan out, steer, inspect, recover, evolve.

### Have an agent write your tests

**You:** "Spin up a BENE agent to cover my auth module with unit tests."

**Claude Code calls:** `agent_spawn`

```json
{"name": "auth-tester", "task": "Write comprehensive unit tests for the authentication module covering login, logout, token refresh, and edge cases."}
```

**Claude Code reads the result back:** agent `auth-tester` (ID: 01HXY...) produced 15 unit tests, and the reply summarizes their coverage.

### Seed files first, refactor second

**You:** "I want an agent loaded with code I already have — the refactor comes after."

**Claude Code calls:** `agent_spawn_only`

```json
{"name": "refactorer"}
```

**Claude Code calls:** `agent_write`

```json
{"agent_id": "01HXY...", "path": "/src/payments.py", "content": "def charge(amount): ..."}
```

**Claude Code calls:** `agent_write`

```json
{"agent_id": "01HXY...", "path": "/tests/test_payments.py", "content": "def test_charge(): ..."}
```

**Claude Code calls:** `agent_checkpoint`

```json
{"agent_id": "01HXY...", "label": "before-refactor"}
```

**You:** "Now let it refactor."

**Claude Code calls:** `agent_spawn`, giving it a fresh task that points at the files already in place.

### Review code from four angles at once

**You:** "Give me four reviews of this code in parallel — security, performance, style, test coverage."

**Claude Code calls:** `agent_parallel`

```json
{
  "tasks": [
    {"name": "security-reviewer", "prompt": "Review this code for security vulnerabilities: ...", "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "performance-reviewer", "prompt": "Review this code for performance issues: ..."},
    {"name": "style-reviewer", "prompt": "Review this code for style and best practices: ..."},
    {"name": "test-reviewer", "prompt": "Suggest test cases needed for this code: ..."}
  ]
}
```

**Four results come back; Claude Code folds them into one unified review.**

### Pause an agent, look around, continue

**You:** "Hold the refactorer for a moment — I want to look over its progress."

**Claude Code calls:** `agent_pause`

```json
{"agent_id": "01HXY..."}
```

**You:** "Looks fine. Carry on."

**Claude Code calls:** `agent_resume`

```json
{"agent_id": "01HXY..."}
```

### Audit what an agent actually did

**You:** "Walk me through everything the refactorer changed."

**Claude Code calls:** `agent_query`

```json
{"sql": "SELECT event_type, payload, timestamp FROM events WHERE agent_id = '01HXY...' ORDER BY event_id"}
```

**Claude Code calls:** `agent_ls`

```json
{"agent_id": "01HXY...", "path": "/"}
```

**Claude Code calls:** `agent_read`

```json
{"agent_id": "01HXY...", "path": "/src/payments.py"}
```

**Claude Code walks you through the event history and the file as it now stands.**

### Watch token spend across running agents

**You:** "Which agents are live right now, and what have they spent in tokens?"

**Claude Code calls:** `agent_status`

```json
{"status_filter": "running"}
```

**Claude Code calls:** `agent_query`

```json
{"sql": "SELECT a.name, SUM(tc.token_count) as tokens, COUNT(tc.call_id) as calls FROM agents a LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id WHERE a.status = 'running' GROUP BY a.agent_id"}
```

**Claude Code lays out the live agents alongside their token totals.**

### Undo a refactor gone wrong

**You:** "That refactor was a mistake. Take the agent back to the earlier checkpoint."

**Claude Code calls:** `agent_query`

```json
{"sql": "SELECT checkpoint_id, label, created_at FROM checkpoints WHERE agent_id = '01HXY...' ORDER BY created_at"}
```

**Claude Code spots the checkpoint labeled "before-refactor".**

**Claude Code calls:** `agent_restore`

```json
{"agent_id": "01HXY...", "checkpoint_id": "01HABC..."}
```

**Claude Code calls:** `agent_diff`

```json
{"agent_id": "01HXY...", "from_checkpoint": "01HABC...", "to_checkpoint": "01HDEF..."}
```

**Claude Code reports the rollback:** back at the pre-refactor state, with 3 files modified and 1 file added (now removed) — all undone.

### Let the meta-harness optimize for you

**You:** "Optimize my text-classification harness with a Meta-Harness search."

**Claude Code calls:** `mh_search`

```json
{"benchmark": "text_classify", "max_iterations": 10, "candidates_per_iteration": 2}
```

**The frontier comes back:** 23 harnesses evaluated across 10 iterations; top accuracy 87% (harness 01HXY1F...); best cost efficiency 45 tokens/prediction (harness 01HXY1G...).

**You:** "Full frontier, please."

**Claude Code calls:** `mh_frontier`

```json
{"search_agent_id": "01HXY..."}
```

### Recover a crashed search

**You:** "The search died at iteration 4 — pick it up where it stopped."

**Claude Code calls:** `mh_resume`

```json
{"search_agent_id": "01HXY...", "benchmark": "text_classify"}
```

**Claude Code reports:** resumed at iteration 4, ran through 10 iterations total, 23 harnesses evaluated, best accuracy 87% (harness 01HXY1F...), and 4 harnesses sit on the Pareto frontier.

---

## What the CLI-first path adds

- **CLI first.** Every command takes `--json`, so an agent can shell out to `bene --json ls` rather than carry MCP schemas in context — which saves the per-call schema overhead.
- **Big results don't flood the wire.** When an agent's output runs past 4KB, the full text lands in its VFS at `/result.txt`; over MCP you get a preview plus a pointer to fetch the rest with `agent_read`.
- **The JSON-RPC stream stays clean.** On stdio startup, the server points `sys.stdout` at `sys.stderr`, so stray library logging can never corrupt the protocol.
- **Searches outlive the connection.** `mh_search` and `mh_resume` hand work to detached worker processes; an MCP disconnect doesn't kill a running search. Workers log to `bene-worker-*.log`.
- **Three commands joined the CLI:** `bene read`, `bene logs`, and `bene mh search --dry-run`.
