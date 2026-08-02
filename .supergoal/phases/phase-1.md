SUPERGOAL_PHASE_START
Phase: 1 of 6 — ADR + schema + contract
Task: Write the ADR (14 answers) and create the additive 4-table truth schema + Fact/Belief/Decision/Conflict contract.
Type: brownfield · core-infra · kernel-feature
Mandatory commands: uv run python -m pytest tests/kernel/test_truth.py -v ; uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py ; uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py
Acceptance criteria: 9
Evidence required: pytest schema output+exit; sqlite_master/PRAGMA dump; ADR section count; ruff exit codes
Depends on phases: none

## Why

The contract and schema are load-bearing; the ADR forces every definitional question to be answered before code locks it in.

## Work

- Write `docs/adr/0001-belief-fact-contract-and-truth-maintenance.md` (create `docs/adr/`). Answer ALL 14 ADR questions, each as its own `##` section:
  1. What is a Fact? 2. What is a Belief? 3. What is a Decision? 4. What is a Conflict? 5. Fact vs Claim? 6. Claim vs Belief? 7. Stable reconciliation key? 8. How does scope work? 9. Lifecycle states? 10. Which beliefs admissible for context/promotion/action? 11. Why deterministic reducer? 12. Why LLM extraction/semantic interpretation OUTSIDE core? 13. Why SQLite is enough for v1? 14. How this later serves agentdex-cli + eddie-agi-kb?
  - State the schema (4 tables + columns), reconciliation rules 1–10, and the single-active-belief DB invariant in the ADR.
- Create `bene/kernel/truth/` package:
  - `schema.py`: `TRUTH_SCHEMA_VERSION = 1`, `TRUTH_SCHEMA_SQL` (all `CREATE ... IF NOT EXISTS`), `ensure_truth(conn)` idempotent + concurrency-safe (`INSERT OR IGNORE` into `truth_schema_version`, mirroring `ensure_v2`'s rationale). Four tables:
    - `belief_facts`(fact_id PK, kind, subject, relation, value, value_hash, scope DEFAULT 'global', source, source_type, confidence REAL, observed_at, expires_at, run_id, agent_id, trace_id, evidence_uri, derived_from DEFAULT '[]', metadata DEFAULT '{}', unsafe INTEGER DEFAULT 0, reconciled_at, created_at). `kind` CHECK in the 6 fact kinds. agent_id is plain TEXT (nullable, NO FK). Indexes on (subject,relation,scope), kind, source_type, reconciled_at.
    - `beliefs`(belief_id PK, subject, relation, value, value_hash, scope, lifecycle CHECK in 6 states, confidence, active_from, active_until, derived_from DEFAULT '[]', last_decision_id, admissible_for_context INTEGER DEFAULT 0, admissible_for_promotion INTEGER DEFAULT 0, admissible_for_action INTEGER DEFAULT 0, created_at, updated_at). Partial unique index: `CREATE UNIQUE INDEX IF NOT EXISTS idx_beliefs_active_key ON beliefs(subject,relation,scope) WHERE lifecycle='active'`.
    - `belief_decisions`(decision_id PK, belief_id (nullable — no-op/rejected facts), rule, from_lifecycle, to_lifecycle, reason, fact_id, admissible_for_context, admissible_for_promotion, admissible_for_action, metadata DEFAULT '{}', created_at). Index on belief_id, rule.
    - `belief_conflicts`(conflict_id PK, subject, relation, scope, belief_id, fact_id, kind, resolution, decision_id, created_at). Index on (subject,relation,scope).
    - `truth_schema_version`(version PK, applied_at).
  - `contract.py`: frozen-ish dataclasses `Fact`, `Belief`, `Decision`, `Conflict`; constants `FACT_KINDS`, `BELIEF_LIFECYCLES`, `UNRELIABLE_SOURCE_TYPES = frozenset({"failed","unreliable","untrusted","error"})`, rule-name constants; `validate_fact(...)`; `value_hash(value)` = `genome_hash({"value": value})` (reuse `bene/kernel/genome_canonical.py`).
  - `__init__.py`: export `ensure_truth`, `TRUTH_SCHEMA_VERSION`, contract classes + constants (API funcs added in later phases).
- Wire `ensure_truth(conn)` into `bene/kernel/schema_v2.py::ensure_v2` (call it at the end — additive, does not change `kernel_schema_version`).
- `tests/kernel/test_truth.py`: schema tests (tables exist, columns present, partial unique index present, idempotent double-run, ensure_v2 creates truth tables, kind/lifecycle constants, value_hash canonicality, no ALTER of legacy tables).

## Acceptance criteria (all must pass — verify each in transcript)

- `ensure_truth(conn)` creates exactly `belief_facts`, `beliefs`, `belief_decisions`, `belief_conflicts`, `truth_schema_version` (verified by querying `sqlite_master`).
- `belief_facts` and `beliefs` expose `subject`, `relation`, `scope`, `value`, `value_hash` as real columns (`PRAGMA table_info`), not JSON-only.
- A partial unique index enforces one `active` belief per `(subject,relation,scope)` (verified via index list / `sqlite_master`).
- `ensure_truth` is idempotent: running twice leaves exactly one `truth_schema_version` row and raises no error.
- `ensure_v2(conn)` also creates the 4 truth tables AND still creates the legacy v2 tables (engrams etc.).
- `FACT_KINDS == {observation,claim,state,hypothesis,decision,policy}` and `BELIEF_LIFECYCLES == {candidate,active,superseded,quarantined,expired,rejected}`.
- `value_hash(1) == value_hash(1.0)` and `value_hash("a") != value_hash(1)`.
- ADR file exists and contains a `##`/`###` section answering each of the 14 questions (≥14).
- No legacy table is ALTERed (diff has no `ALTER TABLE agents|files|blobs|tool_calls|state|events|checkpoints|memory|shared_log|agent_skills`).

## Mandatory commands (run each, surface last ~10 lines + exit code)

- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py`

## Evidence required in transcript

- pytest output (schema tests pass) + exit code
- a `sqlite_master` + `PRAGMA table_info` dump proving the 5 tables, key columns, and the partial unique index
- `grep -c` of the 14 ADR question sections + the question titles
- ruff check + format exit codes

## Notes

Follow `ensure_v2`'s idempotency comment style verbatim in spirit. Keep all DDL `IF NOT EXISTS`. Do NOT FK `belief_facts.agent_id`. value/value_hash and the reconciliation key MUST be real columns. Reuse `genome_hash`; do not write a parallel canonicalizer.
