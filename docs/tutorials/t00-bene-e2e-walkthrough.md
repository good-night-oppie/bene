# BENE in 10 Minutes: An End-to-End Walkthrough

*Spawn an agent. Watch it work. Audit what it did. Roll it back if it went wrong. Send the whole engagement to a teammate as a single `.db` file.*

This tutorial is the **start-here** entry point. It exercises every BENE subsystem you'll reach for in real triage and SDLC work — Virtual Filesystem (VFS), checkpoints, the audit trail, the dashboard, and the meta-harness — without any deep dive. Each subsystem links out to its own guide for the next level of detail.

![BENE — isolated agent workspaces, durable execution, reusable knowledge](hero-v04.png)


---

## Prerequisites

| Need | How to get it |
|---|---|
| BENE installed | `git clone https://github.com/good-night-oppie/bene.git && cd bene && uv sync` |
| LLM access | One of: Anthropic API key, OpenAI API key, local vLLM, or a Claude Code subscription. `bene setup` walks you through the choices. |
| ~10 minutes | A coffee. |

---

## Step 1 — Initialize a project (30s)

```bash
bene setup        # interactive: pick model preset, write bene.yaml, init bene.db
bene demo         # optional: seed the database with realistic agent data
bene ui           # opens the web dashboard
```

The dashboard is where you watch agents while they work. See [Dashboard](../dashboard.md) for the Gantt view, agent inspector, and live event feed.

---

## Step 2 — Spawn one agent (1 minute)

```bash
bene run "Review src/payments.py for SQL injection vulnerabilities" --name security-review
```

What just happened:

1. BENE created an entry in the `agents` table with status `running`.
2. A new isolated VFS was scoped to this agent's `agent_id`.
3. The agent has its own filesystem inside `bene.db` — it cannot see other agents' files.
4. Every file read, every tool call, every state change is appended to the `events` table as it happens.

Inspect the agent in real time:

```bash
bene ls                          # show all agents and status
bene status <agent-id>           # detailed view of one agent
bene logs <agent-id> --tail 20   # last 20 events
```

Background and isolation tiers live in [Architecture](../architecture.md). The full table layout lives in [Schema](../schema.md).

---

## Step 3 — Checkpoint before risky work (10s)

Snapshots are cheap because the blob store is content-addressed; identical files share a single SHA-256-keyed blob.

```bash
bene checkpoint <agent-id> --label "before-fix"
```

Checkpoint, restore, and diff are the *containment* primitive — see [Checkpoints](../checkpoints.md) for snapshots, surgical restore, and the diff view.

---

## Step 4 — Run something risky in parallel (2 minutes)

Run three agents concurrently. Each lives in its own VFS, so they cannot stomp each other.

```bash
bene parallel \
  -t impl   "Refactor src/payments.py to use parameterized queries" \
  -t tests  "Add pytest unit tests for SQL parameterization" \
  -t docs   "Update API.md with the new query interface"
```

The dashboard shows three Gantt rows side by side. When all three finish, query the results across agents with SQL — that's the point of having every agent in one database:

```bash
bene query "SELECT a.name, COUNT(tc.call_id) AS calls, SUM(tc.token_count) AS tokens
            FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
            GROUP BY a.agent_id"
```

Full pattern catalogue lives in [Use Cases](../use-cases.md). For the live AI-coding workflow, see [MCP Integration](../mcp-integration.md).

---

## Step 5 — Audit what an agent did (1 minute)

A single SQL query reconstructs the full sequence of decisions:

```bash
bene query "SELECT timestamp, event_type, payload
            FROM events
            WHERE agent_id = '<agent-id>'
            ORDER BY timestamp"
```

The `events` table is append-only. Nothing is rewritten in place. This is what *trace-based RAG* means in BENE: the next agent can search this trace as its primary corpus. See [Cross-Agent Memory](../memory.md) and [Cross-Agent Skill Library](../skills.md) for how that retrieval works.

---

## Step 6 — Roll back the wrong fix (instant)

```bash
bene restore <agent-id> --checkpoint <checkpoint-id>
```

Restore is a SQL operation — it rewrites the agent's file and state rows to point at the checkpointed blob references. Other agents on the same project are completely unaffected. This is the *containment is non-negotiable* principle in [Design Philosophy](../philosophy.md).

To diff before deciding:

```bash
bene diff <agent-id> --from <cp-A> --to <cp-B>
```

---

## Step 7 — Coordinate risky changes through a vote (optional)

For changes that need consensus — mass-deletes, force-restores, production deploys — use the shared log to require explicit approvals before commit:

```python
from bene.shared_log import SharedLog
log = SharedLog(bene.conn)

intent_id = log.intent("agent-A", "Delete checkpoints older than 7 days")
log.vote("agent-B", intent_id, approve=True, reason="Matches retention policy")
log.vote("agent-C", intent_id, approve=True, reason="Confirmed safe")
decision = log.decide(intent_id, agent_id="agent-A")
if decision.payload["passed"]:
    log.commit("agent-A", intent_id, summary="Removed 47 checkpoints")
```

Full LogAct intent / vote / decide / commit protocol in [Shared Log](../shared-log.md).

---

## Step 8 — Promote what worked (2 minutes)

After a few agents solve similar problems, you'll notice patterns. Save the recipe as a *skill* so the next agent inherits it:

```bash
bene skills save \
  --name parameterize_sql_query \
  --description "Convert string-formatted SQL to parameterized queries; preserve WHERE-clause shape" \
  --template "Find string-formatted SQL in {file}. Replace with {db_driver} parameterized form. Add tests covering {edge_cases}." \
  --tags security,refactor,sql
```

Future agents in any session can search and apply it:

```bash
bene skills search "sql injection" --order success_count
```

Skills are the procedural counterpart to memory. See [Cross-Agent Skill Library](../skills.md) and the [Use Cases — Multi-Agent Co-Evolution section](../use-cases.md#multi-agent-co-evolution-coral) for the auto-discovery variant via meta-harness.

---

## Step 9 — Export the engagement (30s)

The whole `.db` file is portable. You can hand it to a teammate, attach it to a postmortem ticket, or copy it to S3 for cold storage.

```bash
bene export <agent-id> -o agent-snapshot.db   # one agent
cp bene.db full-engagement-$(date +%Y%m%d).db # everything
```

Open it in DBeaver, the `sqlite3` CLI, or any SQLite-compatible tool. Every file, every tool call, every event is queryable.

---

## Where to go next

| If you want to… | Read |
|---|---|
| Understand *why* BENE is shaped this way | [Design Philosophy](../philosophy.md) |
| Set up BENE as an MCP tool inside Claude Code or Cursor | [MCP Integration](../mcp-integration.md) |
| Run the same `.db` workflow against a fully local LLM | [tutorials/t11 — Local Agents with vLLM](t11-local-agents-vllm.md) |
| Spin up N parallel hypothesis agents and compare with SQL | [tutorials/t06 — ML Research Lab](t06-ml-research-lab.md) |
| Automate prompt strategy search for a hard task | [Meta-Harness](../meta-harness.md) and [tutorials/t01](t01-bene-meta-harness.md) |
| See what a real Oppie engagement looks like end-to-end | [tutorials/t02 — End-to-End Self-Healing](t02-e2e-self-healing.md) |
| Look up a single CLI flag | [CLI Reference](../cli-reference.md) |
| Look up an SQL column | [Schema](../schema.md) |
| Deploy BENE in production | [Deployment Guide](../deployment.md) |

---

## What you just exercised

| BENE subsystem | Step in this tutorial | Deeper read |
|---|---|---|
| VFS | 2, 4 | [Architecture](../architecture.md) |
| Checkpoints | 3, 6 | [Checkpoints](../checkpoints.md) |
| Audit trail (event journal) | 5 | [Schema → events](../schema.md#events) |
| Multi-agent isolation | 4, 6 | [Design Philosophy → Containment](../philosophy.md#containment-is-non-negotiable) |
| Shared log + voting | 7 | [Shared Log](../shared-log.md) |
| Skill library | 8 | [Cross-Agent Skill Library](../skills.md) |
| Export / share | 9 | [CLI Reference → export](../cli-reference.md) |

If you ran every step, you've now used the same primitives Oppie Engineering uses for live triage, on-call, and SDLC self-healing.
