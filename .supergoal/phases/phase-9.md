SUPERGOAL_PHASE_START
Phase: 9 of 10 — Port, DevEx & demo 2.0
Task: Wire legacy capabilities through the kernel via adapters, ship the Apple-grade `bene demo` 2.0 + UI trust/engram panels, bump to 0.2.0, update README/CLAUDE.md.
Type: brownfield, feature, ui
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 8
Evidence required: demo run transcript on fresh tmp dir, back-compat test outputs, UI endpoint smoke, version greps, pytest tails
Depends on phases: 4, 5, 6, 7, 8

## Why

Subsumption becomes real (legacy flows through the kernel) and the fifth pillar ships: zero-config, trustworthy, Apple-grade experience.

## Context you need

- Adapters, NOT rewrites: legacy public APIs must keep working byte-for-byte for existing callers. Pattern: optional kernel hook — e.g., MemoryStore.write also emits a semantic engram when a kernel is attached; SkillStore.save emits procedural engram; SharedLog entries mirror as engrams; metaharness gains an opt-in evolve-backend flag; runner gains opt-in ContextOS packing. Feature-flag via config (bene.yaml `kernel: enabled: true`) with sane default ON for new dbs, OFF only if legacy db lacks v2 tables and user disables.
- The demo is the interview-adjacent artifact: `bene demo` must tell the 5-pillar story in <60s, keyless, on a fresh machine. Read the existing demo implementation in bene/cli (and seed_engagement.py) first; extend rather than replace.
- UI: bene/ui/server.py (Starlette, read-only sqlite) + bene/ui/static/index.html. Add engram browser + per-agent trust panel — follow existing endpoint + panel conventions.
- Apple-grade UX bar (pillar 5): first-run guidance (no config → helpful next steps, not tracebacks), consistent --json, progress feedback, error messages that name the fix. Audit the top 10 CLI commands' failure modes.

## Work

- Adapters in bene/kernel/adapters.py (or per KERNEL-SPEC): memory/skills/shared_log/metaharness/runner hooks as above + tests proving legacy behavior unchanged when kernel detached.
- `bene demo` 2.0: seeded story exercising — spawn agents → engrams accumulate → a probe runs (ACCEPT shown) → one mock evolution round (frontier printed) → memory consolidation beat → trust report for an agent → senses manifest. Ends with summary + pointers. <60s, keyless, works in empty tmp dir.
- UI: GET /api/engrams (filter by kind/agent), GET /api/trust/<agent_id>; engram browser panel + trust panel in index.html (keep the BENE design language).
- CLI UX pass: audit top commands for unhelpful failures; add first-run hints; ensure every new command supports --json.
- Version 0.2.0: pyproject.toml, bene/__init__.py, bene/cli/main.py version_option, uv.lock (bene package block), obsidian exporter default, test fixtures referencing version.
- README.md: add 2.0 architecture section (kernel + 5 pillars + ladder diagram), update Architecture tree with bene/kernel/, refresh Credits with the research grounding (link docs/research/SYNTHESIS.md). CLAUDE.md: update architecture map + version + new CLI groups.

## Acceptance criteria (all must pass — verify each in transcript)

- Back-compat: legacy API calls byte-identical with kernel detached (adapter tests); full legacy suite green UNCHANGED
- `bene demo` runs clean in fresh tmp dir, keyless, exercising all 5 pillars (full output pasted; wall time shown <60s)
- Engram + trust UI endpoints return real data (curl smoke pasted); panels present in index.html
- CLI UX: first-run (no db) for `bene ls` gives guidance not traceback (output pasted); all new commands have --json
- Version 0.2.0 in pyproject.toml, bene/__init__.py, CLI --version, uv.lock (grep all four)
- README has 2.0 architecture section; CLAUDE.md updated (greps)
- Adapters emit engrams when kernel attached (integration test)
- Full suite + kernel suite green; ruff check + format clean

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- Demo transcript + timing; back-compat test names; curl outputs; version greps
- pytest tails

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
