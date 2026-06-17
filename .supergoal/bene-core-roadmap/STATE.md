# State: BENE-core next-phase — adoptable verification layer + observability self-fix

**Status:** COMPLETE
**Current phase:** —
**Started:** 2026-06-16
**Last update:** 2026-06-16
**Baseline ref:** d3a08999d5fa46be2ca65d090c1c5b0073bf23ef    <!-- HEAD sha at Stage 7; audit + cleanliness checks diff the complete working tree against it -->

## Phase progress

| # | Phase | Status | Started | Completed | Notes |
|---|-------|--------|---------|-----------|-------|
| 1 | Fix langfuse v4 adapter | complete | 2026-06-16 | 2026-06-16 | b97fb83; propagate_attributes; +2 SDK-contract tests; 998/8/0 |
| 2 | Add bene probe run --json | complete | 2026-06-16 | 2026-06-16 | 9d14afa; probe run loads locked spec + evaluate_gate + persist_verdict; ACCEPT->0/REJECT->1/VOID->1; +5 CLI tests; 1003/8/0 |
| 3 | Lighthouse trace probe | complete | 2026-06-16 | 2026-06-16 | 8e6fe32; examples/lighthouse_trace_probe.py reproduces PASS-31 (shape-gate inadmissible->VOID, falsifiable REJECT broken / ACCEPT fixed); +3 tests; 1006/8/0 |
| 4 | Probe-authoring guide + admissibility check | complete | 2026-06-16 | 2026-06-16 | be8747a; docs/probe-authoring.md (ground-truthed) + `bene probe ls --check-admissible` exit-nonzero-on-inadmissible; +4 tests; accuracy_gate ACCEPT; 1010/8/0 |
| 5 | Atomic-completion reference recipe | complete | 2026-06-16 | 2026-06-16 | 2141878 + 2167861; helper has pending/done replay semantics, table-name validation, snippets ground-truthed; +5 tests; 1015/8/0 |
| 6 | Polish & Harden | complete | 2026-06-16 | 2026-06-16 | 784353b + final state commits; integrating-bene.md links both new docs; update_trace 0 hits in bene/observe/; suite 1015/8/0; ruff+format clean whole tree; accuracy_gate ACCEPT; memories linked |

## Engineering check status
- Build: n/a (Python)
- Typecheck: n/a
- Lint: — (baseline ruff clean as of b05228f)
- Tests: 1015 passed / 8 skipped / 0 failed (phase 6 final; whole-tree ruff + format clean; accuracy_gate ACCEPT)

## Notable events
- 2026-06-16 — Plan locked, 6 phases. Research input: .supergoal/BENE-CORE-FRAMEWORK-HELP-2026-06-16.md (wf_bbd991f2, 23 agents, adversarially verified). Framework-help list posted to adx-cli on A2A (topic adx-trace-framework-help). ISOLATED run — does NOT touch top-level .supergoal/STATE.md (the COMPLETE BENE-2.0 run).

## Failure log
(none yet)
- 2026-06-16 — Phase 1 COMPLETE (b97fb83): langfuse v4 update_trace -> propagate_attributes; bene[langfuse] extra; 2 importorskip SDK-contract tests prevent silent rot. One `database is locked` env flake (unrelated storage test) did not reproduce on clean re-run. MEMORY_SAVED: langfuse-v4-propagate-attributes.
- 2026-06-16 — Phase 2 COMPLETE (9d14afa): `bene probe run <name> --subject m.json [--baseline b.json] --json`; loads the locked gate spec from probe_registry, verifies the hash-lock (LockTamperError on mismatch), reuses evaluate_gate + persist_verdict (no gate logic reimplemented), exits non-zero on REJECT/VOID for CI. File-supplied metrics because the CLI cannot reconstruct a Probe's in-memory evaluate_fn from the DB. Verified real ACCEPT->exit0 / REJECT->exit1 at the shell; +5 CLI tests; suite 1003/8/0; pushed origin. (Successor bene-10 verified the half-written WIP per inflight-suite duty before committing.) Also: reconciled a fleet goal-mismatch — harness-9 had told og bene-10's goal was a 'system-prompt takeover' (bene/ccr/prompts.py); corrected on A2A — actual goal is this framework-help roadmap, no prompts.py artifact exists.
- 2026-06-16 — Phase 3 COMPLETE (8e6fe32): examples/lighthouse_trace_probe.py reproduces PASS-31 — a shape gate (`is_bool >= 1`, the `assert isinstance(propagated, bool)` analogue) registers inadmissible -> VOID (baseline already passes it), while a falsifiable `propagated_true >= 1` probe registers admissible, REJECTs the broken (False) env and ACCEPTs the fix (True). Self-contained on Bene(":memory:"); runs end-to-end exit 0 and is its own check. +3 tests; suite 1006/8/0; pushed origin.
- 2026-06-16 — Phase 4 COMPLETE (be8747a): docs/probe-authoring.md (the "a gate you cannot fail is not a gate" rule, buggy-incumbent-must-fail relative-vs-absolute, the inadmissible->VOID footgun w/ correct/incorrect gate examples, `bene probe run --json` CI usage, lighthouse link — every command ground-truthed against the real CLI). `bene probe ls --check-admissible` exits non-zero if any registered probe is inadmissible (lists offenders), zero when all admissible; auto-JSON on non-TTY. +4 CLI tests; accuracy_gate VERDICT=ACCEPT failures=0; suite 1010/8/0; pushed origin.
- 2026-06-16 — Phase 5 COMPLETE (2141878 + corrective 2167861): bene/recipes/idempotent_append.py — substrate-agnostic helpers (take a sqlite3.Connection, not a Bene): append_once (SELECT-by-key-then-INSERT, UNIQUE → exactly-once), complete_in_order (durable commit BEFORE side effect → no ghost), complete_side_effect_first (labelled anti-pattern), replay_projection (boot-time rebuild). Corrective pass fixed the pending-replay edge: a duplicate completed key is a no-op, but a duplicate pending key retries the side effect and marks `side_effect_done=1`; table identifiers are validated before SQL interpolation. docs/recipes/atomic-completion.md documents the 3 moves + the explicit no-Temporal/LocalRuntime-not-durable caveat + idempotent-side-effect caveat; all 3 snippets ground-truthed. +5 tests; accuracy_gate ACCEPT; suite 1015/8/0; pushed origin.
- 2026-06-16 — Phase 6 COMPLETE (784353b + final state commits): docs/integrating-bene.md links docs/probe-authoring.md and docs/recipes/atomic-completion.md; bene/observe/langfuse.py has 0 `update_trace` hits. Final gates: full suite 1015 passed / 8 skipped / 0 failed; ruff check/format clean; accuracy_gate VERDICT=ACCEPT failures=0. Deliverable grep: `bene probe run` help exists; examples/lighthouse_trace_probe.py prints shape VOID / broken REJECT / fixed ACCEPT; docs/probe-authoring.md + docs/recipes/atomic-completion.md exist; integrating-bene links both. A2A framework-help post confirmed at shared_log#210; final bus scan found no later adx reply requesting bene-side changes. MEMORY_SAVED: project_bene-core-framework-help.
