# BENE Documentation

Run a swarm of AI agents on your own machine, watch every move, and roll back anything they break.

> **Every agent's files, every event, every checkpoint — one SQLite file you can `cp`. Nothing hides in a cloud.**

BENE (Breeding-program Evolutionary Nexus for Engrams) gives each agent a private filesystem, automatic checkpoints, a live dashboard, and an audit trail you can query.

---

## From clone to demo

```bash
git clone https://github.com/good-night-oppie/bene.git && cd bene
uv sync
uv run bene setup       # configure models, init database, install MCP server
uv run bene demo        # see it in action — no API keys needed
```

---

## Drive it from your editor

After `uv run bene setup`, Claude Code, Cursor, and other MCP clients can drive BENE in plain language:

```text
with bene, review my payments module — security agent and test-writing agent in parallel
```

```text
with bene, refactor auth.py — implement, test, and document in parallel
```

```text
with bene, show me all agents that failed in the last run and what errors they hit
```

Client setup and the full 37 MCP tools: [MCP Integration](mcp-integration.md).

---

## How it works

**Virtual filesystem (VFS)** — each agent works in a private filesystem stored inside the database. No agent can read another's files: isolation is a SQL predicate (`WHERE agent_id = ?`), not a convention.

**Checkpoint** — one agent's files plus KV state, frozen at a chosen moment. Restore in milliseconds; diffing two shows what changed. More in [Checkpoints](checkpoints.md).

**Audit trail** — reads, writes, tool calls, state changes, lifecycle events: each lands in the `events` table as one append-only row, queryable in SQL. Layout: [Schema](schema.md).

**Tier router** — the Difficulty-Aware Routing by Tier router matches each task to a model tier: trivial work runs on a local 7B, hard work on a 70B or Claude. Internals: [Architecture](architecture.md).

**Single `.db` file** — no server, no cloud account. One SQLite file to `cp` for backup, open in any SQLite tool, or hand to a teammate.

---

## Pick a guide by job

| When you want to… | Guide | What you get |
|---|---|---|
| Watch live | [Dashboard](dashboard.md) | Gantt timeline of agent activity, per-agent inspector, live events, multi-project views |
| Script it | [CLI Reference](cli-reference.md) | Every command and every flag, documented |
| Undo mistakes | [Checkpoints](checkpoints.md) | Snapshot and restore, diff two checkpoints, auto-checkpointing, storage behavior |
| Share memory | [Cross-Agent Memory](memory.md) | FTS5-searchable memory shared across agents and sessions |
| Reuse skills | [Skill Library](skills.md) | Shared procedural skill templates, FTS5-searchable, usage-tracked |
| Coordinate decisions | [Shared Log](shared-log.md) | LogAct protocol: declare intent, vote, decide |
| Tune the harness | [Meta-Harness](meta-harness.md) | Automated search over prompts and strategies |
| Borrow a pattern | [Use Cases](use-cases.md) | Code-review swarms, parallel refactors, self-healing agents, post-mortems, incident response, ML research |

---

## Proof: tutorials and case studies

**Component-deep**:

| Tutorial | Focus |
|---|---|
| [t11 — Local Agents with vLLM](tutorials/t11-local-agents-vllm.md) | Zero-cost, auditable local multi-agent stack — vLLM + Tier + Claude Code MCP |

**Full walkthroughs** (complete operational stories):

| Tutorial | Scenario |
|---|---|
| [t00 — End-to-End Walkthrough](tutorials/t00-bene-e2e-walkthrough.md) | Start here. Spawn → run → checkpoint → audit → restore → export |
| [t01 — Meta-Harness 48% to 83%](tutorials/t01-bene-meta-harness.md) | Automated prompt-strategy search in 15 iterations, $0.14 |
| [t02 — End-to-End Self-Healing](tutorials/t02-e2e-self-healing.md) | Wrong-fix detection, surgical rollback, root cause from audit trail |
| [t03 — Security Swarm](tutorials/t03-security-swarm.md) | 4 parallel auditors, SQL findings aggregation |
| [t04 — Migration Rollback](tutorials/t04-migration-rollback.md) | 2M-row backfill anomaly, 0.3s surgical rollback |
| [t05 — Incident Response](tutorials/t05-incident-response.md) | 12-second root-cause from event journal SQL |
| [t06 — ML Research Lab](tutorials/t06-ml-research-lab.md) | 4 hypothesis agents overnight, SQL-comparable results |
| [t07 — Regression Guard](tutorials/t07-regression-guard.md) | Model swap blocked, Meta-Harness restores baseline |
| [t08 — 100-Agent Scale](tutorials/t08-hundred-agents-scale.md) | 847 agents at scale, hub coordination, 2.45M tokens saved |
| [t10 — Self-Healing CI Overnight](tutorials/t10-ci-overnight-bene-swarm.md) | Regression gate, auto-fix, review and refactor swarms in GitHub Actions |

**Case studies** (real Oppie engagements):

| Case study | Result |
|---|---|
| [cs02 — Self-Healing CI](case-studies/cs02-ci-self-healing-refactor-swarm.md) | Multi-agent CI design, insights, supply-chain practices, cross-team influence |

---

## Example scripts

In [`examples/`](../examples/) at the repo root:

- `library_basics.py` — VFS operations, no LLMs involved
- `code_review_swarm.py` — 4 review agents in parallel
- `parallel_refactor.py` — implement, test, document simultaneously
- `self_healing_agent.py` — checkpoint, auto-restore on a failed run
- `autonomous_research_lab.py` — N hypothesis agents, results compared in SQL
- `meta_harness_*.py` — prompt and strategy optimization, automated

---

## Look it up

| Reference | What you get |
|---|---|
| [Schema](schema.md) | The 11 SQLite tables — every column, every index |
| [Architecture](architecture.md) | Subsystems, data movement, design-decision reasoning |
| [Deployment](deployment.md) | Setting up vLLM, production config, Docker |

---

## Build it into your agent

| Guide | What you get |
|---|---|
| [Integrating BENE](integrating-bene.md) | The honest map: what's turnkey vs what you wire yourself |
| [Probe authoring](probe-authoring.md) | Write a kill gate that can actually fail, then wire it into CI with `bene probe run --json` |
| [Atomic completion recipe](recipes/atomic-completion.md) | Exactly-once, ghost-free completion on a plain SQLite/JSONL log — no Temporal dependency |

---

## Why it's built this way

[Design Philosophy](philosophy.md) explains why BENE adopts published research instead of inventing its own, what qualifies a technique for integration, and what comes next.
