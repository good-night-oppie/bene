SUPERGOAL_PHASE_START
Phase: 5 of 10 — Trust & falsifiable-eval layer
Task: Implement falsifiable probes with hash-locked kill gates, the experiments journal, and the per-agent trust ledger + CLI surfaces.
Type: brownfield, feature
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 7
Evidence required: tamper-detection test output, admissibility test output, trust CLI --json output, pytest tails
Depends on phases: 4

## Why

KAOS-parity eval discipline plus the user's trust pillar: engineers trust agents because every mechanism claim is falsifiable and every agent action auditable.

## Context you need

- KERNEL-SPEC.md defines the APIs. KAOS's pattern to improve on (read /home/admin/gh/kaos/CLAUDE.md "v0.9 falsifiable-eval discipline" + kaos/eval/harness/ source): pre-registered gate spec, sha256 lock, harness refuses edited locks, self-falsification admissibility (a probe whose baseline cannot trigger a kill gate is INADMISSIBLE), verdicts ACCEPT/REJECT/VOID, no retune-and-rerun.
- BENE 2.0 improvement over KAOS: probes/verdicts/experiments are ENGRAMS (kind=eval, kind=experiment) with provenance to the probed mechanism — queryable through the same substrate as everything else, not a side system.
- Trust ledger: computed, not declared — per-agent trust summary derived from verifiable events: checkpoint coverage (checkpoints per N events), probe pass rate, audit-trail completeness (tool calls with recorded results / total), provenance depth. Simple deterministic formulas; document them.
- CLI lives in bene/cli/main.py (click groups, --json convention everywhere).

## Work

- bene/kernel/eval/probe.py — Probe base: gate spec (list of named gates w/ predicate descriptions + thresholds), register() computes sha256 lock over canonical JSON of the spec, run(subject, baseline) → Verdict; refuses to run if stored lock hash ≠ recomputed hash (tamper detection).
- bene/kernel/eval/gates.py — gate evaluation helpers + KNOWN_LOCK_SHA256-style registry persisted as engrams.
- bene/kernel/eval/verdict.py — Verdict (ACCEPT/REJECT/VOID + per-gate results), persisted as eval engram with provenance.
- Admissibility self-test: before a probe is usable, it must demonstrate its baseline triggers ≥1 kill gate (i.e., the probe CAN kill); inadmissible probes are marked VOID-at-registration.
- bene/kernel/trust.py — TrustLedger.summary(agent_id) → dict of the four computed signals + composite score; persists trust engrams; documented formulas in docstrings.
- Experiments: every probe run + (later) evolution run logged as experiment engrams; query API.
- CLI: `bene probe ls/show/run-selftest`, `bene trust <agent_id>`, `bene experiments ls/show` — all with --json.
- tests/kernel/test_eval.py + test_trust.py: tamper test (edit stored spec → refuses), admissibility test (gate-less probe → VOID), verdict persistence + provenance, trust formulas on synthetic event streams, CLI smoke via click runner.

## Acceptance criteria (all must pass — verify each in transcript)

- Tamper detection: edited gate spec refuses to run (test output shown)
- Admissibility: probe whose baseline can't trigger any kill gate is VOID/INADMISSIBLE (test shown)
- Verdicts persisted as eval engrams with provenance to probed mechanism (test)
- Trust summary computes all 4 documented signals + composite on a synthetic agent (CLI --json output pasted)
- `bene experiments ls --json` returns logged probe runs
- ≥20 new tests passing
- Full suite green; ruff check + format clean

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- Tamper + admissibility test outputs
- bene trust --json real output
- pytest tails

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
