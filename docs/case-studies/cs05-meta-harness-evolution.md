# The Breeding Program: Evolving a Harness Behind a Kill-Gate

*Engineering · 2026-06*

---

## Context

A harness — the control-flow program that wraps a model: how it plans, when it
retries, what it retrieves, how it gates itself — is usually hand-tuned. Someone
tweaks a prompt, runs a few tasks, decides it "feels better," and ships it. That
loop has two failure modes baked in: it does not scale past a handful of knobs,
and it promotes on vibes — a strategy that looked good in a demo, not one that
provably beat the incumbent.

This case study is about the alternative BENE ships: **breed** harness strategies
across generations on a benchmark, and promote a candidate only when it clears a
held-out kill-gate. It is the Bene Gesserit breeding program as an engineering
loop — patient, multi-generation selection, with no candidate advanced on
appearance.

## Problem framing

Optimizing a harness automatically has three traps:

- **Search that overfits.** Tune against the same tasks you score on and you
  breed a strategy that memorizes the benchmark, not one that generalizes.
- **Promotion by self-report.** If a candidate's own run decides whether it
  ships, you get self-certifying progress — the exact thing eval-probes exist to
  prevent.
- **One-number tunnel vision.** Collapsing "better" to a single score hides the
  trade-offs (accuracy vs cost vs latency) that actually matter.

## Design

### Reflective mutation across generations

The search proposes harness variants by *reflective mutation* — a GEPA-style
loop that reads what failed and rewrites the strategy, generation over
generation, rather than random search. Each candidate is a real, runnable
harness program in the archive.

```bash
bene mh search --benchmark agentic_coding -n 20 -k 4   # 20 generations, 4 candidates each
bene mh status                                          # how the run is progressing
```

### A Pareto frontier, not a single winner

Candidates are scored on multiple objectives and kept as a frontier, so the
trade-offs stay visible instead of being averaged away:

```bash
bene mh frontier                 # the non-dominated set
bene mh inspect <harness-id>     # one candidate: source, scores, trace summary
```

### Promotion behind a held-out kill-gate

This is the load-bearing decision. A candidate is auto-promoted only when it
passes a probe on a **held-out** slice it never trained against — the same
falsifiable, hash-locked kill-gate every other claim in BENE faces. A gate the
incumbent already passes is inadmissible; a candidate that only wins on the
training tasks never ships.

> The promotion gate is the breeding program's selection pressure. Weaken it and
> you breed benchmark-memorizers; keep it honest and you breed generalizers.

### Discoveries persist

What the search learns — which mutations tend to help, which dead-end — is kept
in a persistent knowledge base, so later searches start from the accumulated
lessons rather than from scratch:

```bash
bene mh knowledge                # discoveries carried across searches
```

## Insights

- **Search and score must not share tasks.** Held-out evaluation is the
  difference between breeding a generalizer and breeding an overfit.
- **Promotion is a gate, not a vote.** Tying advancement to a kill-gate the
  candidate could have failed is what makes automated evolution trustworthy —
  the same rule the rest of BENE lives by, applied to BENE's own strategies.
- **Keep the frontier.** Multi-objective selection preserves the trade-offs a
  single score would erase, so you choose a strategy with eyes open.

## What to take from this

If you are hand-tuning prompts and shipping on feel, you are doing selection
without selection pressure. Put your strategies in an archive, evolve them
against a benchmark, and gate promotion on a held-out probe that could kill the
candidate. That is the breeding program — automated improvement that cannot
quietly cheat, because it answers to the same gate as everything else.
