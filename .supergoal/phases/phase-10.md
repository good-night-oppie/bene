SUPERGOAL_PHASE_START
Phase: 10 of 10 — Polish & Harden
Task: Full gates, edge-case + security hardening, claims-vs-implementation audit, corrupt-test regeneration, and the Apple kit refresh against implemented reality.
Type: brownfield, polish, hardening
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 9
Evidence required: full gate outputs, claims-audit excerpts, security grep outputs, demo re-run, kit refresh diff summary
Depends on phases: 1, 2, 3, 4, 5, 6, 7, 8, 9

## Why

"Every aspect perfect" enforced: the final state must match the approved plan, claims must be honest, and the interview kit must reflect what NOW actually runs.

## Context you need

- Two test files were deleted pre-dispatch as unrecoverable 14-byte corruption (gitingest "[Binary file]" placeholders): tests/test_intake.py and tests/test_instrumentation_p0.py. Regenerate them as REAL characterization tests: test_intake.py against bene/intake.py (its public functions/classes — read the module), test_instrumentation_p0.py against the event-journal + tool-call recording surface (bene/events.py + ccr instrumentation paths). ≥8 tests each.
- The claims audit is the honesty backstop: BENE2-DESIGN.md made claims; phases 4–9 implemented them. Every claim must now be marked implemented (test/file ref) or planned (explicitly). Zero false "done" claims — this doc is also interview armor (the candidate can say "here is my claims audit" — that IS the EM-credibility move).
- Apple kit (phase 3) was written when only 0.1.0 ran. Refresh: demo-script-5min.md gets the 2.0 demo beats (re-run every command, paste real output); BILINGUAL §11 one-page glance updated; talk-track facts re-verified. If the interview already happened, refresh anyway (loop rounds follow the screen) and note it.

## Work

- Regenerate the two test files as above; confirm they pass.
- Edge cases (add to tests/kernel/test_hardening.py): empty db kernel init; engram append with missing provenance rejected; concurrent engram writes from two threads (WAL) — no corruption; corrupt/edited lock hash refused; oversized payload (>5MB) handled per blob-store conventions; FTS query with special chars; trust summary for nonexistent agent → clean error.
- Security pass: grep audit that all new SQL is parameterized (no f-string/%-interpolation into execute — show the grep), no secrets/keys in code or docs, no debug prints in bene/kernel/ (grep print( excluding CLI output modules — CLI user-facing prints are legitimate; document the distinction).
- docs/design/CLAIMS-AUDIT.md: table — every claim from BENE2-DESIGN.md (walk its pillar sections + subsumption table) → implemented (file + test ref) | planned (where tracked). Include the subsumption table verdict column: which KAOS/the 0.1.0 predecessor capabilities are now demonstrably subsumed vs pending.
- Docs coherence: every relative link in README.md, docs/design/*, docs/research/* resolves (script the check); architecture trees match reality (diff `ls bene/kernel/` vs documented tree).
- Apple kit refresh as above (re-run demo commands; update one-page glance; add "what changed since the screen" note if applicable).
- Final `bene demo` re-run on fresh tmp dir, output pasted.
- Memory writeback: write/update project memory file (project_bene2.md) in /home/admin/.claude/projects/-home-admin/memory/ — location, version 0.2.0, pillar status, ROADMAP link, interview-kit location; link from MEMORY.md.

## Acceptance criteria (all must pass — verify each in transcript)

- tests/test_intake.py + tests/test_instrumentation_p0.py regenerated, ≥8 tests each, passing
- Hardening tests: all 7 listed edge cases covered and passing
- Security greps clean (parameterized SQL, no secrets, no stray debug prints in kernel) — outputs pasted
- CLAIMS-AUDIT.md exists; zero claims marked implemented without a file+test ref (spot-check 5 shown); subsumption verdict column complete
- All doc links resolve (checker output pasted)
- Apple kit demo script re-verified with real 0.2.0 output; BILINGUAL one-page glance updated
- `bene demo` fresh-dir run pasted, clean
- MEMORY_SAVED: project_bene2 (file exists, linked from MEMORY.md)
- All four mandatory commands exit 0

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- Gate outputs; claims-audit excerpt; security grep outputs; link-checker output; demo re-run; memory file path

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md. After this phase, run the FINAL AUDIT per .supergoal/PROTOCOL.md before printing SUPERGOAL_RUN_COMPLETE.]
