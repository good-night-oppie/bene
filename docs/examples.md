# Examples gallery

Real, runnable example scripts that ship with BENE, grouped by the pillar they
exercise. Each lives under [`examples/`](../examples/) in the repo.

**Two kinds.** *Standalone* examples run against a fresh `bene.db` with no
external services — verified to exit 0 on a clean `pip install bene`.
*Model-backed* examples drive an agent loop and need a configured model provider
(a local vLLM endpoint or an API key in your `bene.yaml`); they are marked below.

Run any of them with:

```bash
uv run python examples/<name>.py     # from a source checkout
```

> The `examples/` scripts ship with the source repo, **not** the PyPI package —
> clone the repo (or copy a script) to run them.

## Per-agent VFS & state

| Example | What it shows | Runs |
|---|---|---|
| [`library_basics.py`](../examples/library_basics.py) | The `Bene` API end to end: create agents, write/read the per-agent VFS, set state, list. | standalone ✓ |
| [`export_share.py`](../examples/export_share.py) | Export one agent to a standalone `.db` and import it elsewhere — the single-file Nexus as a portable artifact. | standalone |

## Checkpoints & recovery

| Example | What it shows | Runs |
|---|---|---|
| [`post_mortem.py`](../examples/post_mortem.py) | Post-mortem debugging: checkpoint, inspect the event journal, and diff to find where a run went wrong. | standalone (args: `<database.db> <agent-id>`) |
| [`self_healing_agent.py`](../examples/self_healing_agent.py) | An agent that checkpoints before a risky step and restores on failure (the Litany loop). | model-backed |

## Engrams & cross-agent memory

| Example | What it shows | Runs |
|---|---|---|
| [`memory_search.py`](../examples/memory_search.py) | The cross-agent memory store: write knowledge from one agent, retrieve it from another. | standalone ✓ |

## Eval-probe kill-gates

| Example | What it shows | Runs |
|---|---|---|
| [`lighthouse_trace_probe.py`](../examples/lighthouse_trace_probe.py) | A falsifiable probe end to end: a shape gate registers *inadmissible* → VOID, while a falsifiable gate REJECTs a broken run and ACCEPTs the fix. Self-contained on `Bene(":memory:")`. | standalone ✓ |

## Shared-log coordination & multi-agent

| Example | What it shows | Runs |
|---|---|---|
| [`shared_log_coordination.py`](../examples/shared_log_coordination.py) | The append-only coordination log: the intent → vote → decide → act protocol across agents. | standalone ✓ |
| [`safety_voting.py`](../examples/safety_voting.py) | A policy-enforced safety gate built on the shared log: human-in-the-loop + multi-agent consensus before a risky action. | model-backed |
| [`code_review_swarm.py`](../examples/code_review_swarm.py) | A fan-out of reviewer agents coordinating findings over the shared log. | model-backed |
| [`parallel_refactor.py`](../examples/parallel_refactor.py) | Many agents refactoring in parallel, each isolated, results merged. | model-backed (illustrative — read it for the pattern) |

## Evolutionary meta-harness search

The `meta_harness_*` scripts each breed a harness for a different benchmark
domain; all are model-backed (they run a search loop). They share one shape —
seed a harness, mutate across generations, promote behind a kill-gated probe.

| Example | Domain |
|---|---|
| [`meta_harness_coding.py`](../examples/meta_harness_coding.py) | agentic coding |
| [`meta_harness_math.py`](../examples/meta_harness_math.py) | math reasoning |
| [`meta_harness_support_tickets.py`](../examples/meta_harness_support_tickets.py) | support-ticket triage |
| [`meta_harness_fraud_detection.py`](../examples/meta_harness_fraud_detection.py) | fraud detection |
| [`meta_harness_crm_campaigns.py`](../examples/meta_harness_crm_campaigns.py) | CRM campaigns |
| [`meta_harness_clv_prediction.py`](../examples/meta_harness_clv_prediction.py) | CLV prediction |
| [`autogenesis_heldout_loop.py`](../examples/autogenesis_heldout_loop.py) | held-out promotion loop (gate that can't see the test set) |

## Research labs

| Example | What it shows | Runs |
|---|---|---|
| [`autonomous_research_lab.py`](../examples/autonomous_research_lab.py) | A multi-agent research workflow orchestrated on one BENE database. | model-backed |
| [`multi_gpu_research.py`](../examples/multi_gpu_research.py) | Fan-out research across multiple local model endpoints. | model-backed |

---

*Standalone examples are verified to exit 0 against a clean install; model-backed
examples need a provider configured in `bene.yaml`. Source: `examples/` in the
repo — the gallery links resolve to the copied scripts on the docs site.*
