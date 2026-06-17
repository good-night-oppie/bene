# BENE Dashboard

One browser tab shows your whole agent fleet live: what's still working, what finished, what died — and the event trail behind every bar.

> **From a red bar to the exact tool call that caused it — without leaving your machine.**

```bash
bene ui           # open the web dashboard
bene demo         # demo data + dashboard (no setup needed)
```

Everything on screen is read from a local SQLite file; remote access stays off until you ask for it with `--host 0.0.0.0`.

## Launch options

```bash
bene ui --port 9000         # custom port (default: 8765)
bene ui --host 0.0.0.0     # bind to all interfaces (for remote access)
bene ui --no-browser        # don't auto-open browser
bene ui --db ./project.db  # specific database
```

## Read the timeline


The centerpiece is a **Gantt timeline**, bucketed into *waves*: agents whose start times cluster together — in practice, one `bene parallel` invocation or one MCP-fired batch.

### Waves

Each wave gets a header card carrying:

- the goal — the wave's task, described in plain English
- when it started, and its total duration
- a status bar split proportionally across completed, running, failed, and killed agents
- pills counting agents per status

### Bars

Beneath it, each agent is one horizontal bar:

- length encodes the agent's runtime, scaled to its wave
- color encodes status — green for completed, purple for running, red for failed, gray for killed or paused
- still-running bars shimmer
- a vertical "now" marker tracks the present moment on active waves
- axis ticks give the scale (0s → Xm)

Hover any bar for a tooltip: name, role, task, status.

### Expand and filter

Clicking a wave's header toggles its rows. Waves unfold on their own while agents are running, and when small (≤12 agents).

The toolbar trims the view:

- the **search box** matches against names, task text, or roles
- the **status pills** isolate a single status — running, done, failed, or killed

## Watch the live feed

A strip along the bottom streams events from all agents as they land: failures, completions, tool calls, file writes. Pills in its header narrow the stream to one event type; clicking an agent ID there jumps the inspector (below) to that agent.

## Inspect one agent

Click a bar in the Gantt (or an ID in the feed) and an inspector panel slides in on the right. Five tabs:

**Overview** — the agent at a glance: status badge, when it was created, its last heartbeat; counters for files written, tool calls, tokens, and recorded events; the full task text; config and metadata JSON.

**Events** — everything the agent has logged, updating live over SSE: lifecycle transitions, state changes, file reads and writes, tool-call starts and ends. New entries arrive without a refresh.

**Tool Calls** — the complete call tree. Each invocation shows its input, its output, how long it took, and its token count; nesting renders as indentation. Expand any row for full input/output detail.

**Files** — a browser for the agent's virtual filesystem. Step into directories, read sizes, climb back out with the breadcrumb.

**Checkpoints** — the agent's checkpoints in order — label, creation time, metadata notes.

## Work over SSH or in CI

No browser on the box? The same data renders as a terminal UI:

```bash
bene dashboard
```

You get a live agent table, per-agent token counts, and an event feed that scrolls.

## Switch between databases

One dashboard serves many projects: pick a different `.db` file from the top-bar dropdown and the view swaps without a restart. **+ Project** loads a database from any path; the same switch works as a URL parameter:

`http://localhost:8765/?db=/path/to/bene.db`
