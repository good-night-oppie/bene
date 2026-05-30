# Phase 1 — bene working plan

**Created:** 2026-05-30
**Spec:** `.harness/spec.md` (bootstrap version — pending operator review)
**Reference impl:** https://github.com/good-night-oppie/ionq (`ionq.evolve` + `ionq.runner` + cross-agent stores)

## ⚠️ Phase 1 framing conflict — operator decision pending

After bootstrap, operator handed over `/tmp/bene-situation-ab-memo.md`
describing a different Phase 1 candidate. See `.harness/notes.md` for the
full memo capture.

Two candidate framings:

| Framing | What it is | Cost | Time-to-result |
|---|---|---|---|
| **A. Spec extraction** (current spec.md) | Extract API surface from ionq.evolve → `docs/spec/` for future bene clean-room rebuild | ~4-6h docs | Static deliverable |
| **B. Situation A/B experiment** (memo) | One-line patch + N runs of `scripts/eval_mutate_vs_baseline.py` to measure if `_build_situation_brief()` injection lifts bug_attribution accuracy ≥5% over situation-OFF baseline | ~1h code + 2-4h compute | Concrete experimental finding |

Bootstrap default = **A**. Memo proposes **B**. **B** is more concrete,
time-bounded, and actionable — produces a measured finding rather than a
spec doc. **A** is groundwork for a future rebuild that may or may not
happen.

Operator needs to confirm which is the active Phase 1 before I start
either. If **B**, operator also needs to rewrite `.harness/spec.md` +
`.harness/files-allowed` (both are agent-deny-listed per my own bootstrap
rule).

## Plan A (spec extraction) — original bootstrap below

> Below remains the original Phase 1 plan as initially bootstrapped. If
> the operator confirms Plan A, proceed as-is. If Plan B wins, this
> section becomes "Plan A — deferred until after Plan B lands".

## Goal (Plan A)

Extract a complete, implementation-independent API spec for bene into
`docs/spec/`. No Python code in `src/bene/` this phase.

## Approach — module by module, breadth-first

For each target module, read the reference counterpart in ionq, write a
spec page that captures:
- public surface only
- intent + contract (not algorithm)
- behavioral examples (input → output shape)
- design constraints (what implementer MUST honor)

Order chosen to minimize forward-reference between modules:

### Foundation (no dependencies)

1. **`docs/spec/core.md`** — VFS engine
   - Source: `ionq/core.py` `class ionq`
   - Surface: `spawn`, `write`, `read`, `delete`, `ls`, `stat`, `exists`,
     `checkpoint`, `restore`, `set_state`, `get_state_or`, `status`,
     `set_status`, `list_agents`, `get_or_create_singleton`, `complete`
   - Why first: foundation that all other modules use

### Cross-agent stores (depend on core)

2. **`docs/spec/skills.md`** — THE MOAT
   - Source: `ionq/skills.py` `class SkillStore`, `class Skill`
   - Surface: `save`, `search`, `get`, `list`, `record_outcome`, `delete`,
     `stats`, `Skill.apply`, `Skill.params`

3. **`docs/spec/memory.md`**
   - Source: `ionq/memory.py` `class MemoryStore`, `class MemoryEntry`
   - Surface: `write`, `search`, `list`, `get`, `delete`

4. **`docs/spec/shared_log.md`**
   - Source: `ionq/shared_log.py` `class SharedLog`
   - Surface: `log_intent`, `log_vote`, `log_decision`, `log_commit`,
     `log_result`, `log_abort`, `tail`, `list`

### Agent execution (depends on core + stores)

5. **`docs/spec/runner.md`**
   - Source: `ionq/runner/runner.py` `class Runner`
   - Surface: `run_agent`, `run_parallel` + `ToolDefinition` contract

### Evolutionary search layer (depends on all above)

6. **`docs/spec/candidate.md`**
   - Source: `ionq/evolve/harness.py` `class Candidate`,
     `class EvaluationResult`, `class SearchConfig`
   - Surface: factory + `validate_interface` contract

7. **`docs/spec/evaluator.md`**
   - Source: `ionq/evolve/evaluator.py` `class Evaluator`
   - Surface: `evaluate`, `evaluate_parallel`

8. **`docs/spec/proposer.md`**
   - Source: `ionq/evolve/proposer.py` `class ProposerAgent`
   - Surface: `propose`, archive-tool contract

9. **`docs/spec/search.md`**
   - Source: `ionq/evolve/search.py` `class Search`
   - Surface: `run`, `run_seeds_only`, `resume` + lifecycle contract

### Cross-cutting

10. **`docs/spec/CONTRACT.md`** — cross-module invariants:
    - VFS isolation guarantee (no cross-agent state leak)
    - Skill / memory persistence semantics (cross-run, audit-trail)
    - Pareto frontier contract (non-domination definition)
    - Checkpoint atomicity (snapshot/restore round-trip)
    - Audit trail completeness (event journal coverage)

11. **`docs/spec/SUMMARY.md`** — index + Phase-1 done marker
    - Links to all spec pages
    - Phase 2 enablement: when this lands + operator review pass, Phase 2
      may start (implementation)

## Task list

- [x] 1. `docs/spec/core.md`        — committed 939b79a
- [x] 2. `docs/spec/skills.md`      — committed 939b79a
- [x] 3. `docs/spec/memory.md`      — committed 939b79a
- [x] 4. `docs/spec/shared_log.md`  — committed 939b79a
- [x] 5. `docs/spec/runner.md`      — committed 87f617e
- [x] 6. `docs/spec/candidate.md`   — committed 87f617e
- [x] 7. `docs/spec/evaluator.md`   — committed 87f617e
- [x] 8. `docs/spec/proposer.md`    — this batch
- [x] 9. `docs/spec/search.md`      — this batch
- [x] 10. `docs/spec/CONTRACT.md`   — this batch
- [x] 11. `docs/spec/SUMMARY.md`    — this batch
- [ ] Operator review pass (pending — see SUMMARY.md sign-off block)

## Spec-page template (use for all 9 module pages)

```markdown
# bene.<module>

> One-paragraph intent statement.

## Public surface

### `<function or class signature>`

**Intent:** what the caller wants to accomplish

**Args:**
- `arg1: type` — meaning
- `arg2: type` — meaning

**Returns:** `type` — meaning

**Pre-conditions:**
- ...

**Post-conditions:**
- ...

**Raises:**
- `<ExceptionClass>` — when

**Behavioral example:**
```python
result = bene.module.function(input)
# result == expected_shape
```

(Repeat per public function / method.)

## Implementer notes

- Constraint 1 the implementer MUST honor
- Constraint 2
- ...

## Cross-references

- Depends on: `bene.<other-module>`
- Used by: `bene.<other-module>`
```

## Done when

- All 11 spec pages exist
- No `src/bene/` Python files created
- No `tests/` files created
- Operator review pass (manual sign-off)
