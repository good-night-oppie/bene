SUPERGOAL_PHASE_START
Phase: 6 of 6 — Polish & Harden
Task: Final green sweep — suite/lint/accuracy-gate clean, docs cross-linked + ground-truthed, A2A reaction loop closed, project memory written, all commits pushed.
Type: brownfield, framework
Mandatory commands: uv run --extra a2a python -m pytest tests/ -q, uv run ruff check bene/ tests/, uv run ruff format --check bene/ tests/, uv run python scripts/landing_copy_linter/accuracy_gate.py check, git --no-pager log --oneline -10
Acceptance criteria: 9
Evidence required: final suite summary (0 failed) + ruff clean + accuracy gate VERDICT=ACCEPT, grep proving the 5 deliverable artifacts + update_trace removal, A2A bus check, git log showing pushed commits + HEAD==origin
Depends on phases: 1, 2, 3, 4, 5

## Why
Enforce "every aspect is perfect" — the whole deliverable set is green, accurate, internally consistent, and the adx reaction loop is closed.

## Work
- Re-run full suite + ruff (check + format) + accuracy gate; fix any drift.
- Update docs/integrating-bene.md to link docs/probe-authoring.md + docs/recipes/atomic-completion.md.
- Ground-truth spot-check (>=3 snippets across the new docs executed live).
- Check the A2A bus: confirm the framework-help post landed; capture any adx reply in STATE.md notable events.
- Write project_bene-core-framework-help.md memory (location, what shipped, status).
- Push all bene-core commits to origin (rebase-on-reject); confirm HEAD==origin/main.

## Acceptance criteria (all must pass — verify each in transcript)
- full suite 0 failed (record the count; invariant is 0 failed)
- ruff check bene/ tests/ clean AND ruff format --check bene/ tests/ clean
- accuracy_gate check -> VERDICT=ACCEPT
- no update_trace anywhere in bene/observe/; bene probe run exists; examples/lighthouse_trace_probe.py runs; docs/probe-authoring.md + docs/recipes/atomic-completion.md exist
- docs/integrating-bene.md links both new docs
- all new docs pass a ground-truth spot-check (>=3 snippets executed live, output matches)
- the A2A framework-help post is confirmed on the bus; any adx reply captured in STATE.md notable events
- MEMORY_SAVED line printed (project memory written)
- all bene-core commits pushed to origin (rebase-on-reject), HEAD == origin/main

## Mandatory commands (run each, surface last ~10 lines + exit code)
- uv run --extra a2a python -m pytest tests/ -q
- uv run ruff check bene/ tests/
- uv run ruff format --check bene/ tests/
- uv run python scripts/landing_copy_linter/accuracy_gate.py check
- git --no-pager log --oneline -10

## Evidence required in transcript
- final suite summary (0 failed), ruff clean, accuracy gate VERDICT=ACCEPT
- a grep proving the 5 deliverable artifacts exist + the update_trace removal
- the A2A bus check (post present, any reply)
- git log showing the pushed commits + HEAD==origin

## Notes
Does NOT touch adx. If an adx reply requests changes, capture it as a notable event + follow-up note — do not expand scope mid-run. Tiny scoped commits; coordinate with bene-9 via A2A if docs/integrating-bene.md is contended.
