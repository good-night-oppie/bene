SUPERGOAL_PHASE_START
Phase: 6 of 6 — Polish & Harden + Delivery (worktree + PR)
Task: Edge/determinism/security hardening, full-suite green, ruff-clean files, then land additively via git worktree + PR.
Type: brownfield · core-infra · kernel-feature · polish
Mandatory commands: uv run python -m pytest tests/ -q ; uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py ; uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py
Acceptance criteria: 6
Evidence required: full test summary+exit (pre-existing failures named); ruff exit codes; git diff --stat; PR URL or branch+command
Depends on phases: 1, 2, 3, 4, 5

## Why

Catch what earlier phases missed (edge cases, determinism corners, stray debug), prove the whole suite is green, then land additively via a reviewable PR.

## Work — sub-passes (each must produce evidence)

- **Edges:** add/verify tests for empty/missing optional fields, long + special-char (unicode/quotes/newlines) subjects/values, multi-key isolation (facts for different `(subject,relation,scope)` keys never cross-contaminate), and bulk reconcile (e.g. 50+ facts across several keys).
- **Determinism/idempotency re-proof:** the replay-from-scratch equality + reconcile-twice no-op tests run as part of the full suite (already added P3 — confirm green).
- **Security/safety:** confirm validation on all emit inputs; confirm the north-star invariant (quarantined/expired/superseded/rejected never `admissible_for_promotion=1`) holds across the suite; grep the truth package for f-string SQL (`f"...SELECT`/`f"...INSERT`/`.format(` in queries) → must be ZERO (parameterized only).
- **Honesty:** review CLI/help copy (reads well, no debug placeholders); confirm no work-trace / agent-session / Status-LOC-Verdict text leaked into `docs/`.
- **Diff review:** `git diff` (working tree) for stray `print(`/debug, TODO/FIXME from this run, dead imports in the new files → clean.
- **Regression sweep:** full `uv run python -m pytest tests/ -q`. If any failures exist, prove they pre-date this run (run the same on the baseline ref / show they don't touch truth) and name them; new code must add 0 new failures.
- **Delivery (worktree + PR):** since bene-main is a shared multi-writer checkout — do NOT `checkout -b` in-tree. Instead: capture the new/changed paths (truth package, main.py belief group, tests, ADR, design doc), create a `git worktree add` on a NEW feature branch (e.g. `feat/truth-maintenance`) from the current HEAD, copy the new/changed files into the worktree, commit there with the `Co-Authored-By: Claude Opus 4.8 (1M context)` trailer, push, and `gh pr create` with a body describing the contract, the 10 rules, admissibility, and the test list. If `gh` is unavailable/unauthenticated, leave the committed feature branch + print the exact `gh pr create` command and the PR body.

## Acceptance criteria (all must pass — verify each in transcript)

- Full suite: `uv run python -m pytest tests/ -q` shows 0 failed, OR no NEW failures vs the pre-run baseline (pre-existing failures named + shown to not involve the truth layer).
- `uv run ruff check` and `ruff format --check` on `bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py` are clean (exit 0).
- Parameterized SQL only: grep finds ZERO f-string/`.format` interpolation inside SQL strings in `bene/kernel/truth/`.
- North-star invariant test present + green: no `quarantined`/`superseded`/`expired`/`rejected` belief is ever `admissible_for_promotion=1`.
- `git diff --stat` reviewed; no stray debug/TODO from this run in the new files.
- A PR is opened via `gh pr create` (URL captured) OR a feature branch holds the committed work + the exact `gh pr create` command and PR body are printed.

## Mandatory commands (run each, surface last ~10 lines + exit code)

- `uv run python -m pytest tests/ -q`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py`

## Evidence required in transcript

- Full test summary (passed/failed counts) + exit code; any pre-existing failures named and shown to pre-date this run
- ruff check + format exit codes
- `git diff --stat` summary of the change
- the PR URL, or the feature branch name + the ready-to-run `gh pr create` command + PR body

## Notes

Delivery is outward-facing: build/verify entirely in-tree first; the worktree+PR is the LAST step. Do not push anything until the full suite + ruff are green locally. Keep the PR strictly additive (new files + the `belief` group + the `ensure_v2` one-liner). Follow the repo's tiny-commit / additive discipline. If gh push is blocked, stop at a committed branch and surface the command — do not force anything outward without the gates green.
