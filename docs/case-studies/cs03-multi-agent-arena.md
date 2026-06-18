# A Competitive Coding Arena on BENE: Design at the Substrate Layer

*Engineering · 2026-06*

---

## Context

Put several coding agents in a room, hand them the same real engineering task,
and score who did it best. Simple to say; brutal to run honestly. The moment a
result decides a ranking, every weakness in your substrate becomes an exploit: an
agent that can see a competitor's files, a score with no receipt, a win that
can't be reproduced, a leaderboard that quietly trusts the agent's own claim.

This case study describes the **substrate-layer design** for that kind of arena —
the load-bearing decisions, in the abstract. It is the *pattern*, not any one
product's implementation; the application logic here is pseudo-code on purpose.
What it shows is why a competitive multi-agent platform wants something like BENE
underneath, and how the four guarantees fall out of the primitives.

## Problem framing

An arena is an adversarial environment by construction. To run one where the
ranking means something, the substrate — not the application — has to guarantee
four things:

- **Isolation.** A competitor must not read or write another's workspace.
- **Auditability.** Every scored action needs a durable, tamper-evident receipt.
- **Reproducibility.** Any result must be re-runnable to settle a dispute.
- **Accumulated memory.** The platform should get smarter across matches without
  leaking one match's secrets into another.

If any of these lives in application code, an agent (or a bug) will eventually
route around it. They belong in the substrate.

## Design

Each guarantee maps to one BENE primitive. The arena code stays small because the
hard parts are the engine's job.

| Arena need | BENE primitive | Why it holds |
|---|---|---|
| Isolation | per-agent VFS, SQL-scoped by `agent_id` | an entrant's own `fs_*` tools stay in its namespace (add an OS sandbox + restricted tools for adversarial code — see below) |
| Auditability | append-only event journal + execution traces | every action is a row (append-only by convention; hash-chain for tamper-evidence if the DB is writable) |
| Reproducibility | checkpoint / restore / diff | re-run a match's BENE state from a snapshot (not external side effects) |
| Accumulated memory | engrams + trace retrieval | learn across matches; the kernel retrievers don't filter by agent, so scope hits yourself |

### Isolation — sealed rooms, one file

Each competitor runs as an isolated agent. The engine scopes an agent's own
`fs_*` tools by `agent_id`, so an entrant's reads and writes stay in its
namespace. This is logical isolation in one file — for **adversarial** entrants,
pair it with an OS sandbox and a restricted tool set: the default runner allows
`shell_exec`, and the operator-facing `query`/`agent_read` tools take an explicit
`agent_id`, so neither is a hard cross-agent boundary on its own.

```python
from bene import Bene

arena = Bene("arena.db")            # one auditable file for the whole tournament
for competitor in entrants:         # pseudo-code: your entrant list
    arena.run(name=competitor, task=PROBLEM)   # each gets a sealed workspace
# competitor A's own fs_* tools never resolve to competitor B's /solution.py
```

### Auditability — the receipt is the row

Scoring reads from the journal, never from the agent's self-report. The log is
append-only *by application convention* — for an arena where an entrant or
operator can write the SQLite file, add real tamper-evidence (a hash-chain over
rows, or an append-only store outside the contestant's reach) before treating a
receipt as unforgeable:

```python
# pseudo-code: derive the score from recorded events, not from what the agent said
events = arena.events(agent_id=competitor)        # the durable trace
score  = rubric(events)                            # deterministic over recorded facts
```

A coordination decision (who advanced, who was disqualified) is itself logged
through the shared-log protocol, so the bracket has the same audit trail the
matches do:

```python
from bene.shared_log import SharedLog
log = SharedLog(arena.conn)
log.intent("advance winners of round 1")
log.vote(intent_id, approve=True)
log.decide(intent_id)                              # durable, ordered, replayable
```

### Reproducibility — disputes settled by replay

Before each scored step the arena checkpoints; a contested result is re-run from
the snapshot rather than argued about:

```python
cp = arena.checkpoint(competitor, label="pre-grade")
# ...grade...
arena.restore(competitor, checkpoint=cp)           # rewinds BENE VFS + state
```

`restore` rewinds the agent's BENE-managed VFS and key-value state. Steps that
reached *outside* BENE — a model call, `shell_exec`, network or host-filesystem
side effects — aren't replayed, so a re-run is deterministic only to the extent
the contested work stayed inside the substrate.

### Accumulated memory — smarter across matches, sealed within one

Finished matches leave traces that become engrams. A future match should
retrieve *lessons* (what tends to fail a gate), not raw workspaces — but scope
that retrieval explicitly: the kernel retrievers filter by `agent_id` only when
*recording* the query, so pass the match/agent scope into retrieval (or curate
which engrams are shared) rather than assuming cross-match reads are sealed by
default.

```python
arena.retrieve("common failure modes on refactor tasks")
```

## Insights

- **Push the guarantees down.** Every property an arena needs to be *fair* is a
  property the substrate can enforce and the application cannot be trusted to.
  Isolation-by-SQL-scope and receipts-by-append-only-log are not features you
  bolt on; they are the reason to have a substrate at all.
- **The score is a query, not a claim.** Deriving rankings from the recorded
  journal — never from an agent's self-report — is what makes a leaderboard
  defensible.
- **One file is an operational gift.** The whole tournament is a single SQLite
  database: copy it for a backup, diff it for an audit, hand it to the next shift
  with zero state reconstruction.

## What to take from this

You do not need an arena to want these four properties — any serious multi-agent
system does. The arena just refuses to let you fake them. Build on a substrate
that makes isolation, auditability, reproducibility, and memory the *default*,
and the application on top stays small, honest, and replayable.
