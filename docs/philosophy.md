# BENE Design Philosophy

## What BENE is

**BENE** = **B**reeding-program · **E**volutionary · **N**exus · **E**ngrams — a Bene Gesserit harness.

- **B**reeding-program — the evolutionary meta-harness search: a patient,
  multi-generation selection toward a better harness, the way the Sisterhood
  bred across millennia toward the Kwisatz Haderach.
- **E**volutionary — harness strategies that compound across generations,
  winners persisting forward instead of being re-derived cold.
- **N**exus — the single auditable SQLite database that joins every agent.
  One nexus, one source of truth.
- **E**ngrams — searchable execution **traces**: the corpus for trace-based
  RAG, BENE's version of a Reverend Mother's *Other Memory*. The next agent
  never starts cold; it inherits the ancestral record.

It is the orchestration substrate we use at Oppie to run agents against
real triage, on-call, and SDLC workloads. Every agent gets an isolated
SQLite-backed virtual filesystem, an append-only event journal, and a
checkpoint timeline. Around that core sits a meta-harness that *evolves*
the strategies agents use to do their jobs.

BENE is not a model. It is not a framework that tries to abstract over
LLM providers in clever ways. It is the harness layer that turns
nondeterministic LLM calls into auditable, comparable, reproducible
operational work.

---

## Why a harness at all?

> 兽物的意识无法超越眼前所见，更不会意识到其猎物或将灭绝……它们，只会
> 毁灭，不会创造……兽类的快感局于感官，止于认知……而人，则需框架逻辑，
> 来理解世界……主动选择专注的意识，来搭建思维的框架……体内细胞和神经
> 最深处的意识，驱动着行为……万物，无永恒，忠于意识，生于本能。

A beast's awareness cannot exceed what is directly in front of it. It
reacts to the prey, the threat, the immediate stimulus — and it only
destroys; it does not create. A human needs *framework and logic* to
understand the world: a deliberately chosen, focused consciousness that
builds the scaffolding of thought before acting.

A raw LLM is the beast. It is extraordinary at reacting to what is in the
context window right now, and left to itself it will happily react its way
into a destroyed working tree, a mass-restore, a confident wrong answer.
It has no Other Memory, no nexus, no inner eye on its own path.

BENE is the framework that lets the agent *build* instead of merely react.
The four letters are not decoration — they are the four convictions made
into structure. The **B**reeding-program and the **E**volutionary loop are
how the harness gets better over time instead of the model. The **N**exus
is the single database that makes every action auditable and containable.
The **E**ngrams — the traces — are the memory that turns each turn into
something the next agent can stand on. Together they are the difference
between an LLM that only reacts and an agent that can create.

---

## The two convictions

### 1. Trace-based RAG beats prompt-based RAG for triage

A triage agent's most valuable retrieval target is not "the documentation"
or "the codebase". It is **what an earlier agent already tried, and what
happened next**. BENE makes the trace itself the primary corpus:

- Every tool call, every result, every state transition lands in the
  event journal.
- Every output that mattered is content-addressed in the blob store.
- Every decision is reachable by SQL query, by full-text search, and by
  agent-scoped read.

The next agent doesn't start cold. It opens a file in its own VFS that
already contains the triage history, the failure pattern grouping, the
prior fix attempts, and the rollback markers. **Retrieval over execution
traces** is the differentiator.

### 2. Harnesses should evolve; models should not

We do not fine-tune the LLM for each new triage shape. We evolve the
harness around it: the prompt template, the tool ordering, the retrieval
strategy, the verifier. The meta-harness is a small evolutionary loop
that proposes harness variants, runs them on a benchmark, and keeps the
winners on a Pareto frontier.

This is cheap (no GPUs), reversible (every harness is a code blob with a
hash), auditable (every iteration is in the event journal), and
compounding (winning patterns persist into the project skill library and
seed future searches).

---

## What gets composed

BENE is built from solutions that already work. We did not invent these.
We integrated them and made them compose:

| Capability | Source | What it solves at Oppie | BENE guide |
|---|---|---|---|
| Cross-agent FTS5 memory | claude-mem (Alex Newman) | Triage agents repeating past mistakes across sessions | [memory.md](memory.md) |
| Cross-agent skill library | Zhou et al. 2026 (arXiv:2604.08224) | Agents reinventing the same dashboard query, the same dedup heuristic, the same rollback recipe | [skills.md](skills.md) |
| Shared log + voting coordination | LogAct (arXiv:2604.07988) | Risky changes (kill agent, mass-restore checkpoint) need consensus and an audit trail | [shared-log.md](shared-log.md) |
| Compact context notation (AAAK) | MemPalace | Context bloat eating accuracy and budget on long-running searches | [meta-harness.md](meta-harness.md) |
| Stagnation + co-evolution | CORAL (arXiv:2604.01658) | The proposer plateauing on one harness shape | [meta-harness.md#coral-getting-unstuck-v060](meta-harness.md#coral-getting-unstuck-v060) |
| Failure diagnosis (verifier) | EvoSkills (arXiv:2604.01687) | Opaque failures giving the next iteration nothing actionable | [meta-harness.md](meta-harness.md) |
| Automated optimization | Meta-Harness (arXiv:2603.28052) | Manual prompt engineering that doesn't compound across releases | [meta-harness.md](meta-harness.md) and [tutorials/t01](tutorials/t01-bene-meta-harness.md) |

The VFS engine, checkpoint timeline, event journal, and isolation tiers
are original Oppie work. They are the substrate that makes everything
above composable in one process and one database.

---

## Operating principles

### Trust comes from the audit trail, not from confidence

A triage agent that says "the bug is in module X" and a triage agent that
says "the bug is in module X **and here's the SQL query that found 847
matching `ConnectionPoolError` events between 14:32 and 14:51**" are not
the same agent. BENE is biased toward making the second statement easy
to produce. The event journal is queryable. Token counts, tool calls,
and timing are first-class columns.

### Containment is non-negotiable

Every agent runs in its own VFS. Two parallel triage agents auditing the
same PR cannot stomp each other. A wrong-fix can be checkpoint-restored
in 0.3s without disturbing the other agents on the project. Isolation is
how you let an autonomous agent loose on production-adjacent work
without writing a postmortem about *the orchestration layer*.


### Compounding is the point

The first time an on-call engineer triages an `iss_storage_unreachable`
event with BENE, they are doing investigation. The second time, BENE
already has a saved skill, a prior trace, and a verifier diagnosis from
last week. By the fifth time, the harness has evolved and the agent gets
the right answer in two tool calls. None of this is automatic — it's
what you get when the substrate makes save-once-reuse-everywhere cheap
and the meta-harness rewards what works.

### Reject what you can't reproduce

Every release of BENE is shipped with the harness it ships, the
benchmark it was scored on, the seed runs that produced it, and the
event-journal contents to reconstruct any decision. If you can't replay
it, it didn't happen.

---

## What we don't do

- **We don't reinvent solved problems.** If a paper or open-source
  project already solves it, we integrate and credit.
- **We don't add features without an operator who needs one.** Every
  capability traces back to a triage, on-call, or SDLC workload that
  benefited.
- **We don't hide origins.** Integrations carry a citation in code,
  docs, and the changelog. Read the papers.
- **We don't build abstractions we can't maintain.** A capability that
  breaks composability is not worth shipping.

---

## What's open

We are actively looking for prior art on:

- Sub-agent rollback granularity finer than full-VFS restore.
- Cross-agent trust models richer than binary approve/reject voting.
- Adaptive context budgets driven by task criticality (page-vs-page
  asymmetry).
- Lifecycle policies — when to retire an agent, when to clone, when to
  promote a singleton.

If you've read something relevant, send it through the issue tracker.
Same integration criteria above apply. Credit will be given.

---

## Contributing

BENE is built for Oppie AI Triage and beyond. The most useful contributions are:

1. A research integration you've read and want to land.
2. A bug report with a reproduction case from real operational use.
3. A benchmark result — capability working, or not working, on a real
   triage or SDLC task.

For Oppie-internal contributions, the active backlog is in the
`bene` repo's epic tracker and the engineering-services Jira
queue.
