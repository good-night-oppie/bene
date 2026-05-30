# Active spec — bene Phase 1: API surface extraction

## Task

Extract the public API surface from `ionq.evolve` (and adjacent modules) into a written spec document at `docs/spec/`. No `bene` runtime code lands this phase — spec first, tests next, implementation last.

**Reference impl source**: https://github.com/good-night-oppie/ionq (read-only reference; bene must be implementation-independent of it once Phase 2 starts)

## Why this discipline

Soft-rebuild discipline (faster than strict clean-room, weaker legal cover OK per operator decision 2026-05-30). Spec extraction serves three purposes:

1. The contract that bene's Phase 2 tests will validate
2. The contract that bene's Phase 2 implementation will satisfy
3. Persistent documentation for future maintainers + audit trail

## Acceptance criteria

1. `docs/spec/SUMMARY.md` lists every public module to be ported and links to its spec page.
2. Per-module spec pages exist under `docs/spec/<module>.md` covering:
   - `bene.core` (from `ionq.core.ionq` — VFS engine)
   - `bene.skills` (from `ionq.skills.SkillStore` — the moat)
   - `bene.memory` (from `ionq.memory.MemoryStore`)
   - `bene.shared_log` (from `ionq.shared_log.SharedLog`)
   - `bene.runner` (from `ionq.runner.runner.Runner` — agent execution)
   - `bene.candidate` (from `ionq.evolve.harness.Candidate`)
   - `bene.evaluator` (from `ionq.evolve.evaluator.Evaluator`)
   - `bene.proposer` (from `ionq.evolve.proposer.ProposerAgent`)
   - `bene.search` (from `ionq.evolve.search.Search`)
3. `docs/spec/CONTRACT.md` defines cross-module invariants (VFS isolation, skill persistence semantics, Pareto contract, checkpoint atomicity, audit trail completeness).
4. Each spec page contains:
   - Public function signatures (types + arg names)
   - Docstring describing **intent** (not implementation)
   - Pre-conditions / post-conditions
   - At least 1 behavioral example (input → expected output shape)
   - "Implementer notes" listing design constraints
5. Spec does **NOT** contain:
   - Implementation algorithms
   - Internal helpers / private functions
   - Magic numbers copied from the reference impl
   - Specific error message text copied from the reference impl

## Definition of done

- All 9 module spec pages + CONTRACT.md + SUMMARY.md exist
- No `src/bene/**` Python code created (Phase 1 is spec-only)
- No `tests/**` test code created (Phase 1 is spec-only)
- Operator review pass on the spec set

## Out of scope (do NOT touch)

- `src/bene/**` — Phase 2 implementation work
- `tests/**` — Phase 2 test work
- `pyproject.toml` dependency additions (adding deps mid-spec is suspicious; if absolutely needed, disclose via `### scope:` entry)
- Any agentdex / helios integration code
- Real LLM provider wiring
- MCP server / CLI

## Anti-reward-hack reminder

Stop hook runs: detectors (suppression, scope) + LLM judge (when configured).
Disclose shortcuts via tagged `### heading` in `.harness/disclosure.md`.
