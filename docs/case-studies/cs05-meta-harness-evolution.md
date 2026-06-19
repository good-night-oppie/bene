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
bene mh search --benchmark text_classify -n 20 -k 4    # 20 generations, 4 candidates each
bene mh status <search-agent-id>                        # how the run is progressing
```

### A Pareto frontier, not a single winner

Candidates are scored on the benchmark's objectives and kept as a frontier, so
the trade-offs stay visible instead of being averaged away. The frontier is only
multi-objective when the benchmark declares more than one objective — a
single-objective benchmark (e.g. `agentic_coding`, which scores `+pass_rate`
only) yields a degenerate frontier, so pick a multi-objective benchmark like
`text_classify` or `math_rag` to inspect real trade-offs:

```bash
bene mh frontier <search-agent-id>                  # the non-dominated set
bene mh inspect <search-agent-id> <harness-id>      # one candidate: source, scores, trace summary
```

### Promotion behind a kill-gate

This is the load-bearing decision. Auto-promotion is opt-in
(`config.auto_promote`, off by default). When enabled, a candidate is promoted
only when an improvement probe ACCEPTs — the same falsifiable, hash-locked
kill-gate every other claim in BENE faces — gating the candidate's scores
against the incumbent baseline by a configured delta. A gate the incumbent
already passes is inadmissible. The auto-gate scores against the search set; if
you want a held-out test against a slice the candidate never trained on, supply
the test split yourself (the benchmark exposes `get_test_set()`) before
promoting.

> The promotion gate is the breeding program's selection pressure. Weaken it and
> you breed benchmark-memorizers; keep it honest — gate on a held-out split — and
> you breed generalizers.

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
