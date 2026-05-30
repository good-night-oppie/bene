# Phase 1 — bene API surface extraction (working plan)

**Created:** 2026-05-30
**Spec:** `.harness/spec.md`
**Reference impl:** https://github.com/good-night-oppie/ionq (`ionq.evolve` + `ionq.runner` + cross-agent stores)

## Goal (from spec.md)

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

- [ ] 1. `docs/spec/core.md`
- [ ] 2. `docs/spec/skills.md`
- [ ] 3. `docs/spec/memory.md`
- [ ] 4. `docs/spec/shared_log.md`
- [ ] 5. `docs/spec/runner.md`
- [ ] 6. `docs/spec/candidate.md`
- [ ] 7. `docs/spec/evaluator.md`
- [ ] 8. `docs/spec/proposer.md`
- [ ] 9. `docs/spec/search.md`
- [ ] 10. `docs/spec/CONTRACT.md`
- [ ] 11. `docs/spec/SUMMARY.md`
- [ ] Operator review pass

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
