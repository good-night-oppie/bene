SUPERGOAL_PHASE_START
Phase: 3 of 6 — Lighthouse trace probe
Task: Ship a runnable example reproducing PASS-31 (shape-gate VOID vs falsifiable probe REJECT-on-broken / ACCEPT-on-fixed) plus a test.
Type: brownfield, framework
Mandatory commands: uv run python examples/lighthouse_trace_probe.py, uv run python -m pytest tests/test_lighthouse_probe.py -q, uv run --extra a2a python -m pytest tests/ -q, uv run ruff check examples/lighthouse_trace_probe.py tests/test_lighthouse_probe.py
Acceptance criteria: 6
Evidence required: example stdout showing VOID/REJECT/ACCEPT for the three cases, the admissible vs inadmissible registration statuses, suite summary line
Depends on phases: 1, 2

## Why
A runnable proof that the probe layer catches the exact bug class behind the dogfood stream (a green test passing on a broken value) converts the pitch from slideware to "watch it bite."

## Work
- examples/lighthouse_trace_probe.py on Bene(":memory:") + ensure_v2 + EngramStore: (a) register an isinstance-style shape gate (returns bool, no relative-to-baseline) -> show it registers inadmissible and runs VOID; (b) register a falsifiable propagated_true>=1 probe authored buggy-incumbent-must-fail -> show it registers admissible, REJECTs the broken (propagation=False) subject, ACCEPTs the fixed (propagation=True) subject.
- tests/test_lighthouse_probe.py asserting all three outcomes.

## Acceptance criteria (all must pass — verify each in transcript)
- uv run python examples/lighthouse_trace_probe.py runs end-to-end, exit 0, prints the three verdicts
- the falsifiable probe registers status=="admissible"
- the shape-gate registers status=="inadmissible" and runs VOID
- the falsifiable probe REJECTs the broken subject and ACCEPTs the fixed subject
- tests/test_lighthouse_probe.py passes
- full suite 0 failed; ruff clean on touched files

## Mandatory commands (run each, surface last ~10 lines + exit code)
- uv run python examples/lighthouse_trace_probe.py
- uv run python -m pytest tests/test_lighthouse_probe.py -q
- uv run --extra a2a python -m pytest tests/ -q
- uv run ruff check examples/lighthouse_trace_probe.py tests/test_lighthouse_probe.py

## Evidence required in transcript
- the example's stdout showing VOID / REJECT / ACCEPT for the three cases
- the admissible vs inadmissible registration statuses
- suite summary line

## Notes
Self-contained; the "propagation" metric is a stand-in function returning True/False — the point is the GATE shape, not real langfuse. Reference this example from docs/probe-authoring.md (phase 4). Use the verified bene/kernel/eval API (Probe.register/run, gates relative_to_baseline).
