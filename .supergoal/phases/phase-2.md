SUPERGOAL_PHASE_START
Phase: 2 of 6 — Persistence: emit + queries (TruthStore)
Task: Build TruthStore — emit_fact persisting all reconciliation-critical fields + inspectable belief/fact queries + explain_belief skeleton.
Type: brownfield · core-infra · kernel-feature
Mandatory commands: uv run python -m pytest tests/kernel/test_truth.py -v ; uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py ; uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py
Acceptance criteria: 7
Evidence required: pytest output+exit; raw-SQL dump of one emitted fact row; ruff exit codes
Depends on phases: 1

## Why

Facts must be storable with every reconciliation-critical field intact before any reducer can reason over them; queries provide the inspectable read surface.

## Work

- `bene/kernel/truth/store.py` — `class TruthStore` with `__init__(self, conn)` (call `ensure_truth(conn)` defensively):
  - `emit_fact(self, *, kind, subject, relation, value, scope="global", source=None, source_type=None, confidence=1.0, observed_at=None, expires_at=None, run_id=None, agent_id=None, trace_id=None, evidence_uri=None, derived_from=None, metadata=None, unsafe=False) -> str` — validates kind (via `validate_fact`), mints `ulid`, computes `value_hash`, serializes `derived_from`/`metadata` JSON, defaults `observed_at` to DB now, leaves `reconciled_at` NULL, INSERTs, returns fact_id. Parameterized SQL only.
  - `get_fact(self, fact_id) -> dict | None`
  - `list_facts(self, *, subject=None, relation=None, scope=None, kind=None, reconciled=None, limit=None) -> list[dict]`
  - `list_beliefs(self, *, subject=None, relation=None, scope=None, lifecycle=None, limit=None) -> list[dict]`
  - `list_active_beliefs(self, *, subject=None, relation=None, scope=None, limit=None) -> list[dict]` (lifecycle='active')
  - `get_belief(self, belief_id) -> dict | None`
  - `explain_belief(self, belief_id) -> dict | None` — SKELETON: returns `{belief, facts (from derived_from + key match), decisions: [], conflicts: [], admissibility}`. Decisions/conflicts arrays are wired here (read belief_decisions/belief_conflicts) so P3 only fills the writer side.
  - Internal helpers for inserting belief/decision/conflict rows (used by P3 reducer): `_insert_belief`, `_insert_decision`, `_insert_conflict`, `_set_belief_lifecycle`. Keep them on TruthStore so reducer composes them.
- Module-level convenience wrappers in `__init__.py`: `emit_fact(conn, ...)`, `list_beliefs(conn, ...)`, `list_active_beliefs(conn, ...)`, `get_fact`/`explain_belief` (each constructs a `TruthStore`).
- Extend `tests/kernel/test_truth.py` with emit + query tests.

## Acceptance criteria (all must pass — verify each in transcript)

- `emit_fact` persists ALL reconciliation-critical fields (fact_id, kind, subject, relation, value, value_hash, scope, source, source_type, confidence, observed_at, expires_at, run_id, agent_id, trace_id, evidence_uri, derived_from, metadata, unsafe) — a direct-SQL read returns each supplied value (Test 1).
- `emit_fact` computes/stores `value_hash`, defaults `scope='global'`, sets `observed_at`, leaves `reconciled_at` NULL.
- `emit_fact` raises a clear error for an unknown `kind`.
- Emitting a `claim` fact creates a `belief_facts` row but NO `beliefs` row (Test 2 precondition — reducer not yet run).
- `list_beliefs`/`list_active_beliefs` return inspectable rows; empty DB returns `[]` (no crash).
- `explain_belief` on a missing id returns None/empty (no crash); on a present belief returns belief + source facts (+ empty decisions/conflicts for now).
- Direct-SQL test asserts `SELECT COUNT(*) FROM belief_facts` matches the number emitted (Test 12 — SQLite directly inspectable).

## Mandatory commands (run each, surface last ~10 lines + exit code)

- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py`

## Evidence required in transcript

- pytest output (emit/query tests pass) + exit code
- a transcript dump of one emitted fact row read back via raw `SELECT * FROM belief_facts` showing all fields populated
- ruff check + format exit codes

## Notes

Parameterized SQL ONLY (no f-string value interpolation). Return plain dicts (sqlite3 Row → dict) so output is JSON-serializable for the CLI later. `derived_from`/`metadata` stored as JSON text, returned parsed. Keep insert helpers reducer-friendly; the reducer in P3 must not duplicate persistence logic.
