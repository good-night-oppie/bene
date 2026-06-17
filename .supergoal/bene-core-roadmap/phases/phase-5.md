SUPERGOAL_PHASE_START
Phase: 5 of 6 — Atomic-completion reference recipe
Task: Ship docs/recipes/atomic-completion.md + a substrate-agnostic idempotent-append helper + a test proving exactly-once and ordered-completion-prevents-ghost.
Type: brownfield, framework, ui
Mandatory commands: uv run python -m pytest tests/test_atomic_completion_recipe.py -q, uv run python scripts/landing_copy_linter/accuracy_gate.py check, uv run --extra a2a python -m pytest tests/ -q, uv run ruff check tests/test_atomic_completion_recipe.py
Acceptance criteria: 6
Evidence required: the exactly-once retry demonstration (same key -> no-op -> prior id), the ordered vs unordered partial-failure contrast, suite summary line
Depends on phases: none

## Why
Classes 1 & 2 (the densest P1 cluster) are best fixed by adx NATIVELY; bene-core's job is a substrate-agnostic reference + small helper, NOT a runtime dependency — so adx wires it into its own JSONL log without taking Temporal.

## Work
- docs/recipes/atomic-completion.md: ordering inversion (durable record commits BEFORE the side effect), idempotent append (SELECT-by-(id,idempotency_key)-then-INSERT), projection-rebuild-on-boot (fixes /replay restart-404), with a worked example + the explicit "no Temporal needed; LocalRuntime is not durable across restart" caveat.
- A small substrate-agnostic helper (bene/recipes/idempotent_append.py or a documented function) taking a plain sqlite connection/path — NOT a Bene — demonstrating exactly-once append. (If a standalone module is scope creep, a fully-worked doc example + the test is acceptable, but the test must exist and prove the property.)
- tests/test_atomic_completion_recipe.py: exactly-once under simulated retry + ordered-completion leaves no ghost on mid-sequence failure (vs the buggy write-before-commit variant).

## Acceptance criteria (all must pass — verify each in transcript)
- docs/recipes/atomic-completion.md exists, documents ordering inversion + idempotent append + projection-rebuild, and states the durability caveat (no Temporal dep; substrate-agnostic)
- the helper performs exactly-once append: a replayed write with the same key is a no-op returning the prior id (shown in the test)
- the test simulates a mid-sequence failure and shows the ordered variant leaves NO partial/ghost record (vs the buggy variant which would)
- all doc code snippets are runnable and ground-truthed (no fabricated output)
- tests/test_atomic_completion_recipe.py passes
- full suite 0 failed; ruff clean on touched files

## Mandatory commands (run each, surface last ~10 lines + exit code)
- uv run python -m pytest tests/test_atomic_completion_recipe.py -q
- uv run python scripts/landing_copy_linter/accuracy_gate.py check
- uv run --extra a2a python -m pytest tests/ -q
- uv run ruff check tests/test_atomic_completion_recipe.py

## Evidence required in transcript
- the exactly-once retry demonstration (same key -> no-op -> prior id)
- the ordered vs unordered partial-failure contrast
- suite summary line

## Notes
Keep the helper genuinely substrate-agnostic — takes a connection/path, not a Bene. It is a REFERENCE for adx, not a new bene runtime feature. Do NOT edit the adx repo. Tiny scoped commit.
