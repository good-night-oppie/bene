SUPERGOAL_PHASE_START
Phase: 6 of 10 — Evolution engine
Task: Implement the Breeding Program — GEPA-style reflective evolution with Pareto frontier, trace→skill distillation, strategy genes — promotion gated by phase-5 probes.
Type: brownfield, feature
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 7
Evidence required: offline evolution-loop test output, Pareto frontier dump, promotion-gate test, pytest tails
Depends on phases: 4, 5

## Why

This is where BENE goes beyond both rivals: KAOS's metaharness lacks Pareto multi-objective + gated promotion; bene 0.1.0's skills are static — the Breeding Program with kill gates is the headline capability.

## Context you need

- Papers grounding this (SYNTHESIS.md has details): GEPA (reflective prompt evolution, Pareto frontier — agent-multi-prompt-opt list), Trace2Skill (hierarchical consolidation of trajectory patches), SkillClaw (aggregate multi-trace evolution directions + validation before adoption), SkillX (3-level skill hierarchy: planning/functional/atomic), EvoMap (experience as compact gene control-signals), Meta-Harness (search the harness, not the model).
- KERNEL-SPEC.md defines APIs. Candidates/skills/genes are engrams (kind=strategic/procedural) with provenance to source traces.
- Promotion gate is NON-NEGOTIABLE: no evolved artifact becomes "active" without an ACCEPT verdict from a registered probe (phase 5). This is the Hassabis falsifiability + Karpathy verification-realism fusion — document the connection in module docstring.
- Everything must run OFFLINE in tests: mock reflection function (deterministic string transforms standing in for LLM reflection), mock benchmark (e.g., keyword-matching task with a scoreable fitness). The architecture takes a `reflect_fn`/provider callable so real LLMs plug in later — same pattern as existing bene/metaharness mock usage (read bene/metaharness/search.py + tests/test_metaharness.py for the mock conventions).

## Work

- bene/kernel/evolve/gepa.py — Genome (text strategy + metadata), ReflectiveEvolver: propose mutations via reflect_fn fed with trace-engram feedback, evaluate on benchmark fn → multi-objective scores (quality, cost, tokens), ParetoFrontier (non-dominated set, queryable, persisted as engrams).
- bene/kernel/evolve/distill.py — TraceDistiller: mine trace engrams → candidate skill patches → consolidate into 3-level hierarchy (planning/functional/atomic) → procedural engrams with provenance to every source trace.
- bene/kernel/evolve/genes.py — StrategyGene: compact control-signal encoding attached to candidates; apply/merge operations.
- Promotion: evolve module exposes promote(candidate) which REQUIRES a probe ACCEPT verdict engram; otherwise raises PromotionBlocked.
- Wire experiments journal: every evolution round logs an experiment engram.
- tests/kernel/test_evolve.py — full offline loop: seed genome → 3+ generations on mock benchmark → frontier improves or holds (assert non-domination invariant), distillation from synthetic traces produces 3-level hierarchy, promotion blocked without ACCEPT and allowed with it.

## Acceptance criteria (all must pass — verify each in transcript)

- Offline evolution loop: ≥3 generations, no API keys, completes in test; frontier non-domination invariant asserted
- Pareto frontier persisted + queryable; dump pasted in transcript
- Distillation produces planning/functional/atomic skills with provenance to ALL source trace engrams (test)
- Strategy genes attach to candidates and survive round-trip persistence
- PromotionBlocked without ACCEPT verdict; promotion succeeds with one (both tested)
- Every evolution round visible via `bene experiments ls --json`
- ≥20 new tests passing; full suite green; ruff clean

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- Evolution test output incl. generations + frontier dump
- Promotion-gate test output (both directions)
- pytest tails

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
