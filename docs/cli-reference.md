# BENE CLI Reference

Launch, watch, rewind, and query a fleet of agents from your terminal — every command works against the same local `bene.db` file.

> **Running from a clone:** `bene` isn't on your `PATH` after `uv sync` — prefix every command below with `uv run` (e.g. `uv run bene init`), or `source .venv/bin/activate` once so the bare `bene` commands shown here resolve. (bene is not on PyPI yet.)

> **`--json` is a global flag — put it *before* the subcommand** (`bene --json ls`, not `bene ls --json`, which errors `No such option`). Any output can then feed `jq`, scripts, or another agent framework. (Piped output auto-emits JSON even without the flag.)

```bash
uv run bene --json <command>
```

---

## Get set up

### `bene setup`

One wizard: pick a model preset, get `bene.yaml` generated, the database initialized, and the MCP server auto-installed into Claude Code.

```bash
bene setup
```

Preset choices: Claude (Sonnet), OpenAI (GPT-4o), a local vLLM (7B/70B), or a custom endpoint.

### `bene init`

Create the database — at `./bene.db` by default, or anywhere you point it.

```bash
bene init
bene init --db ./my-project.db
```

### `bene demo`

Zero API keys needed. Stage 1 always runs a keyless (&lt;60s) "kernel story" first — engrams, a falsifiable probe, one round of evolution, consolidation, a trust report, and a senses manifest — then Stage 2 seeds `demo.db` and opens the web dashboard (skip it with `--no-ui`).

```bash
bene demo                # kernel story, then the dashboard
bene demo --no-ui        # run the keyless story and exit (CI-friendly)
bene demo --port 9000
bene demo --no-browser
```

Inside: 3 execution waves — a code review swarm, a parallel refactor, and prod triage.

---

## Start agents

### `bene run`

One prompt, one agent.

```bash
bene run "Refactor auth.py to use JWT tokens" --name auth-agent
bene run "Find security vulnerabilities" --name security --db ./project.db
```

Flags:

- `--name`, `-n` — the agent's name (required)
- `--db` — database path (default: `./bene.db`)

### `bene parallel`

Several agents at once; each `-t name "prompt"` pair adds one.

```bash
bene parallel \
  -t security  "Find vulnerabilities in auth.py" \
  -t tests     "Write unit tests for auth.py" \
  -t docs      "Update API documentation"
```

Flags:

- `-t name prompt` — one agent per pair (repeatable)
- `--db` — which database to use

---

## Watch them live

### `bene ui`

Web dashboard in a browser tab: Gantt timeline, live event feed, agent inspector.

```bash
bene ui
bene ui --port 9000
bene ui --db ./project.db --no-browser
```

More in the [Dashboard guide](dashboard.md).

### `bene dashboard`

The same monitoring, as a terminal TUI.

```bash
bene dashboard
bene dashboard --db ./project.db
```

---

## See what an agent did

### `bene ls`

Every agent, with status and creation time.

```bash
bene ls
bene ls --db ./project.db
bene --json ls | jq '.[] | select(.status == "failed")'
```

### `bene status`

One agent, in detail.

```bash
bene status <agent-id>
bene --json status <agent-id>
```

### `bene logs`

The agent's conversation plus its event timeline.

```bash
bene logs <agent-id>
bene logs <agent-id> --tail 20    # last 20 events
```

### `bene read`

Pull one file out of an agent's virtual filesystem.

```bash
bene read <agent-id> /path/to/file
bene read <agent-id> /src/auth.py
```

### `bene failure localize`

Blame the earliest decisive step in a failed run. It reads the agent's trace engrams — every `run_agent` turn lands one, plus one per tool call (`tool_name`, `status`, `error_message`) by default — builds a timeline, and points at the first error everything downstream followed from.

```bash
bene failure localize <agent-id>
bene failure localize <agent-id> --persist    # record the verdict as a tier-1 episodic engram
bene --json failure localize <agent-id> | jq '.localized, .index'
```

This works on a **real run by default** (no opt-in, no hand-seeding) because the runner emits the per-tool trace engrams `localize` keys on. If a run was executed with `emit_engrams=False` / `kernel.emit_engrams: false`, there are no trace engrams to read and it returns `localized: false`.

---

## Find anything

### `bene search`

Full-text search over every agent's files and state.

```bash
bene search "SQL injection"
bene search "ConnectionError" --db ./project.db
bene --json search "keyword" | jq '.[].path'
```

### `bene query`

Run read-only SQL against the database — safe to hand to an agent. Reads are enforced at the SQLite engine level (`PRAGMA query_only`), so any write — `INSERT`/`UPDATE`/`DELETE`, a `WITH … DELETE` CTE, or a comment-prefixed statement — is rejected by the engine, not by a keyword check that can be worded around. A blocked write raises `PermissionError`.

```bash
bene query "SELECT name, status FROM agents"
bene query "SELECT SUM(token_count) FROM tool_calls"
bene query "SELECT * FROM events WHERE agent_id = 'abc123' ORDER BY timestamp"
```

Tables are listed in the [schema reference](schema.md).

### `bene index`

Write an `/index.md` summary of an agent's files into its VFS, so searches land faster.

```bash
bene index <agent-id>
```

---

## Undo mistakes

### `bene checkpoint`

Snapshot an agent's files and state under a label.

```bash
bene checkpoint <agent-id> --label "before-migration"
bene checkpoint <agent-id> -l "pre-refactor"
```

### `bene checkpoints`

Every checkpoint an agent has.

```bash
bene checkpoints <agent-id>
bene --json checkpoints <agent-id>
```

### `bene diff`

Compare two checkpoints — files added/removed/modified, state changes.

```bash
bene diff <agent-id> --from <checkpoint-id-A> --to <checkpoint-id-B>
```

### `bene restore`

Rewind one agent to a checkpoint; every other agent is untouched.

```bash
bene restore <agent-id> --checkpoint <checkpoint-id>
```

Checkpoint IDs come from `bene checkpoints <agent-id>`.

---

## Stop, move, share

### `bene kill`

Stop a running agent.

```bash
bene kill <agent-id>
```

### `bene export`

Write one agent's full state into its own standalone database file.

```bash
bene export <agent-id> --output agent-snapshot.db
```

### `bene import`

Bring an exported agent back in.

```bash
bene import agent-snapshot.db
```

---

## Plug into Claude Code

### `bene serve`

Expose bene to Claude Code — or any MCP-compatible client — as an MCP server with 37 tools.

```bash
bene serve --transport stdio       # for Claude Code / most clients
bene serve --transport sse         # HTTP/SSE transport
bene serve --port 8765             # custom port (SSE only)
```

Setup steps: [MCP integration guide](mcp-integration.md).

---

## Breed better harnesses

Automated prompt/strategy optimization searches, from the CLI.

```bash
bene mh search -b <benchmark> -n <iterations>   # start a search
bene mh search -b text_classify -n 10 -k 2      # 10 iterations, 2 candidates each
bene mh search -b agentic_coding -n 20 --background   # run detached
bene mh status <search-agent-id>                 # poll progress
bene mh frontier <search-agent-id>               # view best harnesses
bene mh knowledge                                # view persistent knowledge base
bene mh resume <search-agent-id> -b <benchmark>  # resume (benchmark must match original)
```

Details in the [Meta-Harness guide](meta-harness.md).

---

## Flags that work everywhere

| Flag | Description |
|---|---|
| `--json` | Output structured JSON (auto-enabled when stdout is piped) |
| `--db PATH` | Database file (default: `$BENE_DB` or `./bene.db`) |
| `--version` | Print version |
| `--help` | Help for any command |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BENE_DB` | `./bene.db` | Default database path |
| `BENE_CONFIG` | `./bene.yaml` | Config file path |
