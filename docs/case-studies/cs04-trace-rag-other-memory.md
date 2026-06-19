# Other Memory: Trace-Based RAG so the Next Agent Never Starts Cold

*Engineering · 2026-06*

---

## Context

The most expensive thing an agent does is rediscover what a previous agent
already knew. A fresh session opens with an empty context window; whatever the
last shift learned — which test was flaky, which refactor backfired, which gate
rejected which candidate and why — is gone unless someone wrote it down in a form
the next agent can actually find.

Dumping the full history back into context is not the answer: it is expensive,
it blows the window, and it buries the one relevant fact under thousands of
irrelevant ones. This case study is about the alternative BENE ships by default —
**trace-based retrieval**, the engineering behind the Bene Gesserit's *Other
Memory*: the ancestral memory of every Reverend Mother, made queryable.

## Problem framing

You want the next agent to inherit the *path already walked*, not the whole map.
That means three things the substrate has to provide:

- **Capture without ceremony.** If remembering requires a deliberate write step,
  agents will skip it. Memory has to be a side effect of running.
- **Retrieve the relevant slice.** Given a question, return the few traces that
  matter — not a transcript.
- **Stay cheap at scale.** Thousands of runs cannot mean a linear scan or a
  context-window dump.

## Design

### Capture is the default, not a step

Every run drops a tier-0 trace engram automatically. The agent does not "decide
to remember"; the harness records the path as it walks it. The unit is a
*granule* — one compact record of a turn, a tool call, an outcome.

### A compression ladder, not a flat store

Engrams live on a tiered ladder (0–4): raw traces at the bottom, progressively
compressed summaries above. The MemGAS router probes every configured tier,
entropy-routes and weights them, then merges the surviving hits. You query a
slice of the ladder explicitly when you want to (`--tiers` only takes effect
under the MemGAS router, so pass `--memgas` unless you've set
`kernel.memgas.enabled: true` in `bene.yaml`):

```bash
bene retrieve "why did the regression gate reject candidate 7" --memgas --tiers 0,2,3 --k 5
```

### Retrieval that routes, not just matches

Retrieval picks a router: an entropy-aware **MemGAS** router when enabled, or an
adaptive fallback. The point is to return the *informative* traces — the ones
that actually reduce the next agent's uncertainty — rather than the
lexically-nearest ones.

```bash
bene retrieve "common failure modes on auth refactors" --memgas
bene retrieve "common failure modes on auth refactors" --adaptive   # force fallback
```

### Attributable by agent

A query can be attributed to the asking agent. `--agent` tags the query engram
itself for provenance — it records *who asked* — so the query trail is
auditable. It is not an isolation filter: retrieval still searches every agent's
engrams, and memory compounds across the whole system. Pass an existing
`agent_id` (the generated ULID, not the `--name` you gave `bene run`):

```bash
bene retrieve "what broke last time we touched the parser" --agent <agent_id>
```

## Insights

- **Memory has to be free to be used.** Making capture a side effect of running —
  not a discipline agents must remember — is what makes the corpus complete
  enough to be worth retrieving.
- **Compress, don't accumulate.** A flat log of every turn is unsearchable at
  scale; a ladder of summaries the router entropy-weights and merges keeps
  retrieval focused as the corpus grows.
- **Inheritance beats re-derivation.** The measurable win is not "the agent has
  more context" — it is "the agent skips the dead ends the last one already
  mapped." The path walked is the asset.

## What to take from this

If your agents start every session from zero, you are paying the rediscovery tax
on every run. Make trace capture a default of the substrate, put a compression
ladder under retrieval, and let the next agent query the path instead of
re-walking it. That is Other Memory — and it is a `bene retrieve` away.
