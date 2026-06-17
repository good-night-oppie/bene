SUPERGOAL_PHASE_START
Phase: 2 of 6 — Add bene probe run --json
Task: Add a `probe run` CLI subcommand that runs a registered probe and emits the JSON verdict, exiting non-zero on REJECT/VOID so CI can gate on it.
Type: brownfield, framework
Mandatory commands: uv run bene probe run --help, uv run python -m pytest tests/test_cli_probe_run.py -q, uv run --extra a2a python -m pytest tests/ -q, uv run ruff check bene/cli/main.py tests/test_cli_probe_run.py, uv run ruff format --check bene/cli/main.py tests/test_cli_probe_run.py
Acceptance criteria: 7
Evidence required: probe run --help output, a real ACCEPT run + a real REJECT run with exit codes piped through json.load, suite summary line
Depends on phases: none

## Why
Probe verdicts are only reachable via the Python API today (bene probe has only ls/show), so the kill-gate is not CI-wirable — the missing piece that makes the verification-layer pitch adoptable.

## Work
- Add @probe.command("run") in bene/cli/main.py mirroring the `bene --json failure localize` shape: @click.pass_context, load probe by name from probe_registry, supply subject/baseline (smallest real mechanism: --subject/--baseline JSON files of metrics, or a registered subject_ref), call Probe.run(...), _json_out(ctx, verdict_dict), ctx.exit(1) on REJECT/VOID.
- Reuse existing Probe.run / persist_verdict; do NOT reimplement gate logic.
- tests/test_cli_probe_run.py covering ACCEPT, REJECT, VOID(inadmissible) + --json shape + non-zero exit on REJECT.

## Acceptance criteria (all must pass — verify each in transcript)
- uv run bene probe run --help lists the command
- a registered probe whose subject beats baseline -> --json status=="ACCEPT", exit 0
- a probe whose subject fails a gate -> status=="REJECT", exit non-zero
- an inadmissible probe -> status=="VOID", exit non-zero
- --json output is valid JSON carrying at least status, name, gate results
- the command reuses Probe.run / persist_verdict (no gate-logic reimplementation)
- full suite 0 failed; ruff clean on touched files

## Mandatory commands (run each, surface last ~10 lines + exit code)
- uv run bene probe run --help
- uv run python -m pytest tests/test_cli_probe_run.py -q
- uv run --extra a2a python -m pytest tests/ -q
- uv run ruff check bene/cli/main.py tests/test_cli_probe_run.py
- uv run ruff format --check bene/cli/main.py tests/test_cli_probe_run.py

## Evidence required in transcript
- bene probe run --help output
- a real ACCEPT run + a real REJECT run (with exit codes) piped through python -c json.load
- suite summary line

## Notes
How subject/baseline are supplied is a design choice — pick the smallest real one (JSON metrics files are simplest) and document it in docs/probe-authoring.md (phase 4). Keep it real: the command must actually run Probe.run against the registry, not stub a verdict.
