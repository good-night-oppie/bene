SUPERGOAL_PHASE_START
Phase: 4 of 10 — Kernel v2 engram substrate
Task: Implement bene/kernel/ — the unified typed engram store, event bus, and capability registry per KERNEL-SPEC.md, additive to the legacy schema.
Type: brownfield, feature
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 7
Evidence required: new-test count, back-compat test output, lineage query demo, pytest tails
Depends on phases: 2

## Why

"Everything is an engram" is the unifying substrate all four capability layers (phases 5–8) build on — provenance-linked, compression-tiered, searchable.

## Context you need

- Build EXACTLY to docs/design/KERNEL-SPEC.md (phase 2 output) — DDL + API signatures live there. Where the spec is ambiguous, follow existing conventions in bene/schema.py (ULIDs via ulid-py, created_at timestamps, agent_id scoping) and bene/blobs.py (content-addressed zstd blobs).
- Legacy core (bene/core.py, schema.py, events.py, blobs.py) must remain UNTOUCHED except, if strictly needed, a hook point ≤5 lines. Kernel opens the same .db and creates v2 tables additively.
- Engram kinds (minimum): trace, episodic, semantic, procedural, strategic, eval, experiment, trust. Tier field encodes the compression ladder position (0=raw trace … 4=strategic).
- Reuse, don't duplicate: payloads go through the existing blob store; events also mirror into the legacy event journal so the legacy UI/logs still see kernel activity.

## Work

- bene/kernel/schema_v2.py — additive DDL + migration guard (CREATE TABLE IF NOT EXISTS; never ALTER legacy tables); FTS5 virtual table for engram search.
- bene/kernel/engrams.py — EngramStore: append(kind, payload, provenance, parents, tier), get, search(fts + filters), lineage(engram_id, direction=ancestors|descendants), promote(engram_id, new_tier) creating a NEW linked engram (append-only — promotion never mutates).
- bene/kernel/bus.py — EventBus: subscribe(event_type, handler), publish(event) with at-least-once sync dispatch + error isolation (one bad handler doesn't break others); mirror to legacy journal.
- bene/kernel/capabilities.py — CapabilityRegistry: register(name, fn_ref, autonomy_level, description), lookup, list; persisted in v2 table.
- tests/kernel/__init__.py + test_engrams.py, test_bus.py, test_capabilities.py — including: provenance REQUIRED (append without provenance raises — test), old 0.1.0 db opens and legacy tables byte-identical after kernel init (test by checksumming sqlite_master + a legacy table before/after), lineage across ≥3 generations, FTS search, promotion immutability.
- Run ruff format on new files as you go.

## Acceptance criteria (all must pass — verify each in transcript)

- All four kernel modules + schema importable; `python -c "from bene.kernel import EngramStore"` works
- Engram CRUD + FTS search + ≥3-generation lineage query demonstrated in tests
- Promotion creates new linked engram; original unchanged (test)
- Provenance enforcement test passes (missing provenance raises)
- Back-compat test: pre-existing 0.1.0 db opens, legacy schema untouched after kernel init
- ≥25 new tests in tests/kernel/, all passing
- Full legacy suite still green; ruff check + format clean

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- pytest tails for both suites; new-test count
- Back-compat test name + pass shown
- One lineage query result pasted

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
