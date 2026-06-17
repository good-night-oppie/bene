SUPERGOAL_PHASE_START
Phase: 4 of 6 — Probe-authoring guide + admissibility check
Task: Write docs/probe-authoring.md (buggy-incumbent-must-fail rule + CI usage) and add a probe-ls admissibility check that exits non-zero on any inadmissible probe.
Type: brownfield, framework, ui
Mandatory commands: uv run bene probe ls --help, uv run python -m pytest tests/test_cli_probe_admissible.py -q, uv run python scripts/landing_copy_linter/accuracy_gate.py check, uv run --extra a2a python -m pytest tests/ -q, uv run ruff check bene/cli/main.py tests/test_cli_probe_admissible.py
Acceptance criteria: 6
Evidence required: 2+ doc snippets executed live (output matches doc), the admissible(exit0) vs inadmissible(exit non-zero) check runs, accuracy_gate VERDICT line + suite summary
Depends on phases: 3

## Why
Adopters who author naive absolute <=0 gates get inadmissible->silent-VOID no-op probes; the guide + a one-command admissibility check prevent the footgun that would make the layer quietly useless.

## Work
- docs/probe-authoring.md: the admissibility self-test, the buggy-incumbent-must-fail rule, relative-to-baseline vs healthy baseline, bene probe run --json CI usage, a correct-vs-incorrect gate example, link to examples/lighthouse_trace_probe.py.
- bene/cli/main.py: add --check-admissible flag to `probe ls` (or equivalent) that exits non-zero if any registered probe is inadmissible.
- tests/test_cli_probe_admissible.py covering the exit behavior both ways.

## Acceptance criteria (all must pass — verify each in transcript)
- docs/probe-authoring.md exists and documents: admissibility self-test, buggy-incumbent-must-fail rule, probe run --json CI usage, the inadmissible-VOID footgun with correct vs incorrect gate example
- every CLI command/snippet in the doc is ground-truthed (spot-run >=2 in transcript)
- bene probe ls --check-admissible exits non-zero when any probe inadmissible, zero when all admissible
- tests/test_cli_probe_admissible.py passes
- accuracy_gate check -> VERDICT=ACCEPT
- full suite 0 failed; ruff clean on touched files

## Mandatory commands (run each, surface last ~10 lines + exit code)
- uv run bene probe ls --help
- uv run python -m pytest tests/test_cli_probe_admissible.py -q
- uv run python scripts/landing_copy_linter/accuracy_gate.py check
- uv run --extra a2a python -m pytest tests/ -q
- uv run ruff check bene/cli/main.py tests/test_cli_probe_admissible.py

## Evidence required in transcript
- 2+ doc snippets executed live (showing real output matches the doc)
- the admissible (exit 0) vs inadmissible (exit non-zero) check runs
- accuracy_gate VERDICT line + suite summary line

## Notes
Keep the guide tight and example-driven (point at the lighthouse). The check can be a flag on probe ls rather than a new command — smallest real surface. No fabricated output in the doc — run every snippet.
