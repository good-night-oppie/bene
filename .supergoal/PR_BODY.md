## Truth Maintenance layer — deterministic Belief/Fact contract + reducer

BENE's first **Truth Maintenance** layer: a deterministic, SQLite-backed
Belief/Fact contract and reducer that lets BENE distinguish raw observations,
candidate facts, current beliefs, lifecycle decisions, and promotion/action
admissibility. Additive, boring, auditable — a kernel/database feature, not an
AI feature. No LLM, no network, no vector/graph DB, no CLIPS, no daemon.

> North star: BENE must never let future agents evolve from unsafe memories.

### What's in it

- **Schema** (`bene/kernel/truth/schema.py`) — 4 additive tables (`belief_facts`,
  `beliefs`, `belief_decisions`, `belief_conflicts`) + `truth_schema_version`, via
  idempotent `ensure_truth(conn)` (also called from `ensure_v2`). No legacy table
  is ALTERed. DB-enforced invariants: one `active` belief per `(subject, relation,
  scope)` (partial unique index) **and** non-active beliefs can never be
  admissible (CHECK constraint).
- **Contract** (`contract.py`) — `Fact`/`Belief`/`Decision`/`Conflict`, the fact
  kinds + lifecycle states, canonical `value_hash` (via `genome_canonical`:
  `1 == 1.0`, NFC == NFD, num ≠ str), lossless JSON value encode/decode, and
  boundary validation.
- **Reducer** (`reducer.py`) — `reconcile_beliefs` (Rules 1–9) + `quarantine_belief`
  (Rule 10). Deterministic (`ORDER BY observed_at, value_hash, fact_id` — a
  content-stable tie-break so replays agree even for same-timestamp facts),
  idempotent (`reconciled_at` watermark), and every lifecycle transition writes a
  decision row.
- **Store** (`store.py`) — `emit_fact` + inspectable queries + `explain_belief`
  (belief + source facts + decisions + conflicts + admissibility). Parameterized
  SQL only.
- **CLI** — `bene belief emit | reconcile | ls | active | explain | quarantine`,
  all `--json`-aware.
- **Docs** — ADR `docs/adr/0001-…` (14 questions answered) + design doc
  `docs/design/TRUTH-MAINTENANCE.md`.

### The ten reconciliation rules

1 create · 2 supersede (+conflict) · 3 refresh (no dup, confidence = max) ·
4 quarantine (unreliable/unsafe) · 5 expired (no activation) · 6 non-active never
promotable · 7 active admissibility set explicitly by the decision · 8 every
transition has a decision · 9 idempotent re-run · 10 manual quarantine override.

### Tests

`tests/kernel/test_truth.py` (43) + `tests/test_cli_belief.py` (11) = **54 new
tests**, covering all 13 required cases plus determinism/replay, idempotency,
stale-fact handling, the DB-level safety invariant, value type round-trip, and a
no-LLM/no-network AST source-scan. Full suite: **1229+ passed, 0 failed** (zero
regressions vs the pre-change baseline of 1182).

### Hardening

This PR was reviewed by a multi-lens adversarial pass (spec / determinism /
security / additive-safety / correctness), each finding independently
skeptic-verified; all 9 confirmed findings are fixed in-PR (determinism
tie-break, DB-level north-star CHECK, value round-trip, input validation,
refresh-confidence, candidate-state documentation).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
