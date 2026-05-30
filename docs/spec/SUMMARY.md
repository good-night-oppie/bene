# bene API spec — Phase 1 SUMMARY

> Implementation-independent specification of the bene module surface.
> Phase 1 deliverable per `.harness/spec.md`. When this index is complete
> and operator-approved, Phase 2 (implementation + tests) may begin.

**Status**: ✅ Phase 1 complete — all 9 module spec pages + CONTRACT.md
landed 2026-05-30 in a single session via batched commits on `main`.

## What this spec is for

bene is the substrate layer for [agentdex](https://github.com/good-night-oppie/agentdex). This spec captures the public API surface bene MUST expose so consumers (agentdex, future oppie, third-party integrators) can program against a stable contract. The implementation is intentionally NOT specified — implementers are free to derive algorithms independently.

## Reading order

1. **[`core.md`](core.md)** — the foundation (VFS engine, agent lifecycle, files, state, tool calls, checkpoints). Read first; everything else depends on it.
2. **[`skills.md`](skills.md)** — the moat (cross-run procedural memory store with outcome tracking).
3. **[`memory.md`](memory.md)** — cross-agent episodic memory (typed observation/result/insight/error entries).
4. **[`shared_log.md`](shared_log.md)** — LogAct-style coordination log (append-only, position-ordered, intent→vote→decision→commit/result).
5. **[`runner.md`](runner.md)** — agent execution engine (plan-act-observe loop, tool registry, permission policy, usage tracking).
6. **[`candidate.md`](candidate.md)** — evolutionary search data model (Candidate, EvaluationResult, SearchConfig + interface validation).
7. **[`evaluator.md`](evaluator.md)** — runs a Candidate against a Benchmark (hermetic agent per evaluation, dynamic module loading, injected `llm()`).
8. **[`proposer.md`](proposer.md)** — generates new Candidates from archive state (cross-agent archive read, skill+memory context, pivot prompts).
9. **[`search.md`](search.md)** — outer evolutionary search loop (seeds → iterations → frontier → knowledge filing; with resume).
10. **[`CONTRACT.md`](CONTRACT.md)** — cross-module invariants (VFS isolation, persistence semantics, Pareto contract, checkpoint atomicity, audit trail, naming hygiene).

## Module dependency graph

```
┌─────────────────┐
│   bene.core     │  ← foundation (VFS, agents, state, checkpoints)
└────┬────────────┘
     │
     ├─────────────┐──────────────┐──────────────┐
     ▼             ▼              ▼              ▼
 bene.skills   bene.memory   bene.shared_log   bene.runner
     │             │                              │
     │             │                              │
     └──────┬──────┘                              │
            ▼                                     │
     ┌──────────────┐                             │
     │bene.candidate│  (pure data model)          │
     └──────┬───────┘                             │
            │                                     │
     ┌──────┴──────┐                              │
     ▼             ▼                              │
bene.evaluator  bene.proposer ◄───────────────────┘
     │             │
     └──────┬──────┘
            ▼
       bene.search
```

`bene.pareto` (helper module for `compute_pareto` + `ParetoFrontier`) is
referenced by search + proposer; not in the initial 11 spec pages but
will be added as a thin helper page when Phase 2 starts. CONTRACT.md
defines its semantics.

## Phase 2 readiness checklist

Before Phase 2 may start:

- [x] All 9 module spec pages written
- [x] CONTRACT.md written with cross-module invariants
- [x] SUMMARY.md written (this file)
- [ ] **Operator review pass** — pending
- [ ] (Optional) bene.pareto helper page added — Phase 2 may add inline

## Naming hygiene reminder

bene MUST use the canonical names listed in `CONTRACT.md`. The following are FORBIDDEN in new bene code, commits, docs, issues, memory, or mailbox content:

`meta-harness`, `metaharness`, `MetaHarnessSearch`, `mh_*`, `HarnessCandidate`, `HarnessEvaluator`, `ccr`, `ClaudeCodeRunner`

Canonical equivalents:

| Concept | Canonical | (Forbidden legacy) |
|---|---|---|
| Search engine class | `Search` | `MetaHarnessSearch` |
| Candidate data class | `Candidate` | `HarnessCandidate` |
| Evaluator class | `Evaluator` | `HarnessEvaluator` |
| Runner class | `Runner` | `ClaudeCodeRunner` |
| MCP archive tools | `archive_ls`/`archive_read`/`archive_grep`/`archive_submit` | `mh_ls_archive`/`mh_read_archive`/`mh_grep_archive`/`mh_submit_harness` |

## Soft-rebuild discipline (project-level reminder)

bene Phase 1 follows the **soft-rebuild** discipline (per operator decision 2026-05-30):
- Same Claude session may both read the reference impl (ionq) AND write the bene spec — strict clean-room separation was waived
- Reasonable distance: bene-side renames, restructuring where natural, derived algorithms in Phase 2
- Honest provenance: this spec page acknowledges reference impl in the per-module "Reference impl" lines
- NOT airtight legal cover; sufficient for tribe-legibility + brand distance

If stricter discipline is required later (e.g. legal review demands clean-room), Phase 2 implementation can be re-done in a separate session with no access to the reference impl, using only this spec + tests.

## Known gaps documented in the spec

- **`proposer.md` calls out the situation-engine wiring gap** (`_build_situation_brief()` exists in reference impl but never called in `propose()`). See `.harness/notes.md` for the A/B experiment proposal.
- **`runner.md` flags `shell_exec` as dangerous-by-default** — bene MUST decide whether to ship it as a builtin or require opt-in via permission policy.
- **`bene.pareto` helper module not yet spec'd** as its own page; semantics covered in `CONTRACT.md` + cross-references.

## Sign-off block (operator fills in)

```
Operator: ____________________________
Date:     ____________________________
Verdict:  [ ] AGREE — Phase 2 may proceed
          [ ] REVISE — see comments below
Comments:
________________________________________________________________
________________________________________________________________
________________________________________________________________
```
