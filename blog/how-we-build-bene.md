# How We Build BENE: Harness Engineering and Eval-Gated Evolution

*BENE blog · the HOW · 2026-06-18*

[Why](why-bene.html) and [what](what-is-bene.html) are done. This is the *how* —
the method, not just the code. BENE is built the way it asks its agents to
build: in small reversible steps, behind gates that can actually fail, and with
every run leaving memory for the next one. Three loops.

## Loop 1 — the PR loop: harness engineering, not vibe coding

Vibe coding is one giant turn that either lands or doesn't. Harness engineering
is the opposite: **research → plan → implement** in steps small enough to verify
and reverse.

Every change ships as a **tiny PR** from an isolated git worktree, so the shared
checkout is never disturbed and a bad change is one revert away. The work is
planned to disk first (a roadmap, falsifiable acceptance criteria) and only then
executed — the plan is the artifact, the diff is the consequence.

> A change you cannot review in one sitting is a change you cannot trust.

## Loop 2 — the gate loop: a gate you cannot fail is not a gate

Every claim BENE makes about itself must survive a **falsifiable probe** — a
pre-registered, hash-locked check with a verdict of ACCEPT, REJECT, or VOID.

```bash
bene probe ls --check-admissible    # every probe must be able to REJECT
bene --json probe run <name> --subject m.json --baseline base.json
# ACCEPT -> exit 0 ; REJECT / VOID -> exit 1   (--json is a top-level flag)
```

The load-bearing rule is **admissibility**: a probe has to be able to REJECT a
broken baseline *before* it is allowed to ACCEPT a fix. A check the incumbent
already passes proves nothing — it VOIDs instead of rubber-stamping. The gate is
hash-locked so it cannot be quietly loosened to make a failing change pass.

This is the discipline behind the docs you are reading: every command in these
posts was run against the real CLI before it was written down. No fabricated
output.

## Loop 3 — the evolution loop: the breeding program

BENE does not hand-tune its harness strategies — it **breeds** them. A
meta-harness search mutates strategies across generations on a benchmark and
bridges each survivor into the engram store as a tier-4 candidate. Promotion past
the kill-gate is a separate, **opt-in** step (default off, no `mh search` flag):
the search *proposes* candidates; a deliberate auto-promote run — facing the same
kill-gated probe everything else does — *disposes*.

```bash
bene mh search --benchmark agentic_coding --background   # mutate + evaluate (prints a search-agent id)
bene mh frontier <search-agent-id>                       # the Pareto frontier that survived
```

Selection is patient and gated: no candidate promotes by looking good in a demo,
only by passing a held-out gate that could have killed it. Progress that can't be
falsified isn't progress.

## What ties the loops together: memory

Each loop leaves a trace, and traces become **engrams** — searchable memory of
the path already walked. The agent that picks up the next PR, the next gate, the
next generation does not start cold; it retrieves what the last one learned.

```bash
bene retrieve "why did the regression gate reject candidate 7"
```

That is the whole method in one sentence: **small steps, real gates, bred
strategies, durable memory** — and the harness holds itself to it. The framework
that lets an agent build instead of react is built, recursively, by agents
building instead of reacting.

*That closes the opening series. The docs go deeper — start with the
[architecture](../docs/architecture.html) and the case studies.*
