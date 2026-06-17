SUPERGOAL_PHASE_START
Phase: 8 of 10 — Harness-engineering layer
Task: Implement the autonomy ladder with enforcement, agent-senses discoverability manifests, the debt sweeper, and loop guards.
Type: brownfield, feature
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 7
Evidence required: autonomy-denial test output, senses manifest sample, sweeper findings on fixture, loop-guard trip output, pytest tails
Depends on phases: 4

## Why

The OpenAI/LangChain/Claude-Code harness canon as first-class primitives — the layer NEITHER rival has, and the Karpathy autonomy-slider thesis made enforceable.

## Context you need

- Papers/posts (SYNTHESIS.md, harness-engineering list): OpenAI Harness Engineering series (autonomy thresholds ⑧, knowledge discoverability ③/⑤, slop prevention ④/⑥, tech-debt repayment ⑦/⑨, merge philosophy ⑤), LangChain harness series (forced self-checks, loop guards/dead-loop prevention, context injection, compute allocation), Claude Code lessons (tool design for agent legibility), Philipp Schmid (write-for-deletion, data-first harness).
- Autonomy ladder from BENE2-DESIGN.md: L0 (read-only) … L4 (full auto incl. external effects); each capability registered in phase 4's CapabilityRegistry carries an autonomy_level; agents carry a granted level.
- Enforcement is at the registry boundary: a guard wrapper, not scattered if-statements.

## Work

- bene/kernel/harness/autonomy.py — AutonomyPolicy: grant(agent_id, level), check(agent_id, capability) → allow/deny; deny emits a trust-relevant engram (feeds phase-5 trust ledger); decorator/wrapper for capability calls.
- bene/kernel/harness/senses.py — SensesManifest.generate(db) → machine-readable JSON+markdown manifest of: agents + status, capabilities + autonomy levels, available skills, memory domains, recent engram activity summary, entry-point commands — the "what can I discover here" surface an incoming agent reads first (OpenAI discoverability ③/⑤). CLI: `bene senses --json`.
- bene/kernel/harness/sweeper.py — DebtSweeper.scan(agent_id|vfs paths) for slop signatures: debug prints (stack-specific list), stale TODO/FIXME accumulation, duplicated blocks (n-gram window), dead imports (regex-level); emits report engram with findings + locations. CLI: `bene sweep <agent_id>`.
- bene/kernel/harness/guards.py — LoopGuard: sliding-window detector over event stream for repeated near-identical actions (same tool + similar args ≥N times) and oscillation patterns; trips → intervention event engram + configurable callback (default: log + mark agent needs-attention).
- tests/kernel/test_harness_layer.py — L1 agent denied L3 capability (and the denial engram exists), manifest generated from a live tmp db contains all six sections, sweeper finds ≥3 planted slop types in fixture files, loop guard trips on synthetic repeated events and NOT on varied events.

## Acceptance criteria (all must pass — verify each in transcript)

- Autonomy enforcement: L1 agent denied L3 capability; denial recorded as engram (test output pasted)
- Senses manifest from live db has all sections; sample pasted; `bene senses --json` works
- Sweeper finds ≥3 distinct planted slop types with locations (findings pasted)
- Loop guard trips on synthetic loop, stays silent on varied stream (both tested)
- Denials/interventions feed trust ledger signals (integration test with phase 5)
- ≥18 new tests passing
- Full suite green; ruff check + format clean

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- Denial test output; manifest sample; sweeper findings; guard trip output
- pytest tails

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
