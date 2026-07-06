# Truth Maintenance — Facts, Beliefs, Decisions, Admissibility

> BENE must not merely remember what happened. BENE must know which memories are
> safe to believe, safe to place in context, safe to promote from, and safe to
> act on.

This is BENE's first **Truth Maintenance** layer: a deterministic, SQLite-backed
Belief/Fact contract and reducer. It is a database/kernel feature, not an AI
feature. See [ADR 0001](../adr/0001-belief-fact-contract-and-truth-maintenance.md)
for the full rationale.

## The five things BENE keeps separate

- **BENE engrams remember what happened.** Raw, permanent execution traces — the
  existing engram substrate. Truth maintenance never rewrites them.
- **BENE facts structure what was observed or claimed.** A fact is a typed,
  immutable row in `belief_facts`: *subject* stands in *relation* to *value*,
  within a *scope*, seen by a *source* at *observed_at*, with provenance and
  confidence.
- **BENE beliefs represent the current accepted state.** At most one `active`
  belief per `(subject, relation, scope)`, in `beliefs`.
- **BENE decisions explain why the accepted state changed.** One row in
  `belief_decisions` per lifecycle transition: which rule fired, from/to
  lifecycle, the triggering fact, and the reason.
- **BENE admissibility flags decide whether a belief can be used for context, promotion, or action.**
  Three booleans on each belief, set explicitly by the deciding row.

## What this is NOT

This is **not RAG**, **not vector memory**, and **not a full expert system**. There
is no embedding store, no similarity search, no inference engine, no rule
language, no LLM in the loop. It is a small, boring, auditable, **deterministic**
truth-maintenance layer for agent runs: facts in, beliefs out, every transition
explained and replayable.

## Lifecycle

```
                emit fact
                    │
                    ▼
   (Rule 4 unreliable/unsafe) ──► quarantined ◄── (Rule 10 manual quarantine)
   (Rule 5 expired) ──► [no active belief; decision records the rejection]
                    │
        Rule 1 (no active belief for key)
                    ▼
                 active ──── Rule 3 (same value) ──► active (refreshed/linked)
                    │
        Rule 2 (newer, different value)
                    ▼
              superseded   +   new active belief
```

Lifecycle states: `candidate`, `active`, `superseded`, `quarantined`, `expired`,
`rejected`.

## Reconciliation key and scope

The stable key is **`(subject, relation, scope)`** — real, indexed columns, never
buried in JSON. `value` (with a canonical `value_hash`) is what may change for a
key over time.

`scope` is a free-form namespace (`global` by default; e.g. `run:42`, `repo:bene`,
`agent:<id>`). Same subject+relation under different scopes are **different keys**
and never reconcile against each other. Scope is opaque to the kernel — no
ontology, no hierarchy traversal in v1.

## The ten reconciliation rules

1. A valid candidate fact with no active belief for the key creates one `active`
   belief.
2. A newer valid fact, same key, **different** value, supersedes the old active
   belief and creates a new active belief (a conflict row is recorded).
3. A newer valid fact, same key, **same** value, refreshes/links — no duplicate
   belief.
4. A fact from an unreliable/failed source, or one explicitly `unsafe`, is
   `quarantined`, never `active`.
5. An expired fact cannot create an `active` belief.
6. `quarantined`, `expired`, `rejected`, `superseded` (and `candidate`) beliefs
   are **never** admissible for promotion.
7. `active` beliefs are admissible for context/promotion/action only if their
   decision record allows it explicitly.
8. No lifecycle transition occurs without a decision row.
9. Running reconciliation twice over the same facts duplicates nothing.
10. Manual quarantine overrides `active` and records a decision.

### Reliability policy (Rule 4)

A fact is treated as unreliable when its `source_type` is one of
`{failed, unreliable, untrusted, error}` **or** the fact carries `unsafe=1`.
Unknown source types default to reliable, so new producers work without editing
core.

### Admissibility policy (Rules 6, 7)

`active` + reliable + not-expired ⇒ context/promotion/action all true. Every other
lifecycle ⇒ all false. The trio is written on both the belief and the deciding
row, so admissibility is always traceable to a reason. **North star: BENE must
never let future agents evolve from unsafe memories** — Rule 6 is the guardrail.

## Determinism, idempotency, replayability

The reducer consumes only unreconciled facts (`reconciled_at IS NULL`) in a fixed
total order (`observed_at, fact_id`), with pure rule logic. "Now" is resolved once
per run and recorded into every decision, so expiry is not wall-clock-flaky across
a replay. Re-running is a no-op (the watermark); a from-scratch replay over the
same facts reproduces the identical belief set. The one hard DB-level invariant —
a partial unique index on `(subject, relation, scope) WHERE lifecycle='active'` —
guarantees a single current belief per key by construction.

## Provenance and lineage

Every fact carries `evidence_uri` (a pointer to the engram/blob/URL it came from),
`derived_from` (upstream fact/engram ids), `run_id`, `agent_id`, and `trace_id`.
Beliefs keep the `derived_from` facts that produced them and a `last_decision_id`.
Value equality is canonical via
[`bene.kernel.genome_canonical.genome_hash`](../../bene/kernel/genome_canonical.py):
`1 == 1.0 == 1.00`, NFC == NFD, CRLF == LF, while number `1` and string `"1"` stay
distinct. `explain_belief` reassembles the full lineage: belief + source facts +
decisions + conflicts + admissibility.

## CLI

```bash
bene belief emit --json '{"kind":"observation","subject":"svc.api","relation":"status","value":"up","source_type":"tool"}'
bene belief reconcile
bene belief ls                        # all lifecycles
bene belief active                    # only the accepted state
bene belief explain <belief_id>
bene belief quarantine <belief_id> --reason "operator distrust"
```

Every command supports `--json` (auto-enabled when piped) and `--db`.

## Python API

```python
from bene import Bene
from bene.kernel.truth import (
    emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs,
    explain_belief, quarantine_belief, TruthStore, ensure_truth,
)

b = Bene("bene.db")
ensure_truth(b.conn)
emit_fact(b.conn, kind="observation", subject="svc.api", relation="status",
          value="up", source_type="tool")
reconcile_beliefs(b.conn)              # deterministic; idempotent
for belief in list_active_beliefs(b.conn):
    ...                               # read the clean current-state view
```

The API performs no LLM call and no network I/O. It persists facts, runs the
deterministic rules, and returns inspectable data.

## Future consumers (designed for, not yet implemented)

LLM extraction lives *outside* the kernel: producers extract candidate facts and
emit them; BENE core owns deterministic reconciliation. Planned fact catalogs:

### agentdex-cli

| subject.relation | meaning |
|---|---|
| `baseline.status` | did the baseline run pass |
| `baseline.error_type` | classified baseline failure |
| `trace.completeness` | how complete a captured trace is |
| `judge.verdict` | an LLM/judge verdict on an output |
| `mutation_seed.proposed` | a proposed harness mutation |
| `probe.verdict` | a falsifiable probe's ACCEPT/REJECT/VOID |
| `infra_fault.classification` | infra vs code fault classification |

### eddie-agi-kb

| subject.relation | meaning |
|---|---|
| `paper.proposes.technique` | a paper proposes a technique |
| `tool.implements.capability` | a tool implements a capability |
| `concept.alias` | an alias for a concept |
| `claim.freshness` | how fresh a claim is |
| `claim.conflicts_with` | a claim conflicts with another |

### BENE itself

| subject.relation | meaning |
|---|---|
| `tool_call.status` | terminal status of a tool call |
| `checkpoint.restored` | a checkpoint was restored |
| `context.pollution_detected` | context pollution was detected |
| `probe.verdict` | a probe verdict |
| `promotion.blocked` | a promotion was blocked |
| `autonomy.grant` | an autonomy grant |

`scope` keeps each consumer's facts isolated; admissibility gates feed the
existing promotion/autonomy paths when those integrations land.
