SUPERGOAL_PHASE_START
Phase: 4 of 6 — CLI `bene belief …`
Task: Add the `belief` click group (emit/reconcile/ls/active/explain/quarantine) with --json + --db, following BENE CLI conventions.
Type: brownfield · core-infra · kernel-feature
Mandatory commands: uv run python -m pytest tests/test_cli_belief.py -v ; uv run ruff check bene/cli/main.py tests/test_cli_belief.py ; uv run ruff format --check tests/test_cli_belief.py
Acceptance criteria: 8
Evidence required: pytest CLI output+exit; real terminal emit→reconcile→active→explain→quarantine run; ruff exit codes
Depends on phases: 3

## Why

The feature must be scriptable and honest from the command line, matching BENE's existing click + `--json` conventions.

## Work

- In `bene/cli/main.py` add `@cli.group("belief")` def belief(): docstring "Deterministic truth maintenance — facts, beliefs, decisions, admissibility." Subcommands (each `@click.option("--db", default=DEFAULT_DB)` + `@click.pass_context`, open via `_get_afs(db)`, call `ensure_truth(afs.conn)`):
  - `emit` — `@click.option("--json", "payload", default=None)` (the FACT payload string; if `None` or `-`, read from stdin). Parse JSON → `emit_fact(**payload)`. Honor GLOBAL output `--json` via `_json_out(ctx, {"fact_id": fid})`; human line otherwise. Malformed JSON → `_json_err`/clear message + exit 1.
  - `reconcile` — call `reconcile_beliefs(conn)`; `_json_out(ctx, counts)`; human summary `created=… superseded=… refreshed=… quarantined=… rejected=… skipped=…`.
  - `ls` — options `--subject/--relation/--scope/--lifecycle/--limit`; `list_beliefs(...)`; `_json_out` list; human table-ish lines.
  - `active` — options `--subject/--relation/--scope/--limit`; `list_active_beliefs(...)`; `_json_out` list; human lines.
  - `explain` — `@click.argument("belief_id")`; `explain_belief(...)`; `_json_out` object; human render (belief, facts, decisions, conflicts, admissibility). Missing id → clear "not found" + exit 1.
  - `quarantine` — `@click.argument("belief_id")` + `@click.option("--reason", required=True)`; `quarantine_belief(...)`; `_json_out` result; human confirmation. Missing id → clear error + exit 1.
  - Always `afs.close()` in `finally`.
- `tests/test_cli_belief.py` using `click.testing.CliRunner` invoking `bene.cli.main.cli` with a temp `--db` (tmp_path). Cover each subcommand + the end-to-end flow + `--json` validity + error cases. For JSON output use `["--json", "belief", "active", "--db", db]`. For emit payload use `["belief", "emit", "--db", db, "--json", json.dumps({...})]`.

## Acceptance criteria (all must pass — verify each in transcript)

- `bene belief emit --json '{...}'` persists a fact and prints/returns its `fact_id`; reads payload from stdin when omitted or `-`.
- `bene belief reconcile` runs the reducer and prints a summary; global `--json` returns structured counts.
- `bene belief ls` lists beliefs; `bene belief active` lists only active beliefs; both honor `--json`.
- `bene belief explain <belief_id>` returns belief + facts + decisions + conflicts + admissibility; `--json` returns the structured object.
- `bene belief quarantine <belief_id> --reason "..."` quarantines + records a decision carrying the reason.
- End-to-end CliRunner test: emit → reconcile → `active` shows the belief → quarantine → `active` no longer shows it.
- Every subcommand's `--json` output parses as valid JSON (asserted via `json.loads` in tests).
- Unknown belief_id and malformed `--json` payload produce a clear non-crash error (exit code ≠ 0 + message; `--json` error shape when global `--json` set).

## Mandatory commands (run each, surface last ~10 lines + exit code)

- `uv run python -m pytest tests/test_cli_belief.py -v`
- `uv run ruff check bene/cli/main.py tests/test_cli_belief.py`
- `uv run ruff format --check tests/test_cli_belief.py`

## Evidence required in transcript

- pytest output (CLI tests pass) + exit code
- a real terminal run on a temp DB: `belief emit` → `belief reconcile` → `belief active` → `belief explain` → `belief quarantine` (show outputs)
- ruff exit codes; confirm no NEW ruff errors in `main.py` introduced by the added lines (compare to baseline count if main.py has pre-existing drift)

## Notes

The `--json` duality is intentional: global `--json` (before the group) controls OUTPUT; `emit --json` is the fact INPUT payload (different parser levels, no click conflict). Document this in the emit help text. Do not reformat the rest of main.py (avoid touching pre-existing ruff drift). Reuse `_json_out`/`_json_err`/`_get_afs`/`DEFAULT_DB`.
