# Roadmap: BENE Truth Maintenance layer (Belief/Fact Contract + Reducer)

**Task:** Add BENE's first deterministic, SQLite-backed Truth Maintenance layer — a Belief/Fact contract + reducer that distinguishes raw observations, candidate facts, current beliefs, lifecycle decisions, and promotion/action admissibility.
**Type:** brownfield · core-infra · kernel-feature
**Created:** 2026-06-29
**Total phases:** 6

## Context summary

- **Stack:** Python 3, click CLI, single-file SQLite. IDs via `ulid`.
- **Package manager:** `uv` (NEVER pip/poetry).
- **Build / test / lint commands:** `uv sync` · `uv run python -m pytest tests/ -v` · `uv run ruff check .` / `uv run ruff format --check .`
- **Risky areas:** reducer determinism vs wall-clock; idempotency/double-processing; CLI `--json` collision + agent_id FK; repo CI ruff drift (gate on local green).

## Assumptions

Non-blocking decisions recorded here so we can proceed without round-trips. If any are wrong, stop the run and tell us:

- **Home:** new kernel subpackage `bene/kernel/truth/` (mirrors `eval/`, `memory/`), 4 tables created by an idempotent `ensure_truth(conn)` with its own `truth_schema_version`; also invoked from `ensure_v2`. No legacy table is ALTERed.
- **Standalone MVP:** facts/beliefs are their own tables. They *reference* engram/run/agent/trace ids as opaque provenance (`evidence_uri`, `derived_from`) but do NOT deep-wire into the engram substrate or the promotion/runner paths yet. Future consumer integrations (agentdex-cli, eddie-agi-kb) are documented, not implemented.
- **agent_id nullable, no hard FK** on `belief_facts` (facts may originate outside BENE agents).
- **Value equality** reuses `bene/kernel/genome_canonical.py::genome_hash` (int==float, NFC==NFD; num≠str).
- **Reliability policy:** `UNRELIABLE_SOURCE_TYPES = {failed, unreliable, untrusted, error}` + explicit `unsafe=1` → quarantine; unknown source_types default reliable.
- **Admissibility default:** active+reliable+not-expired ⇒ context/promotion/action all True; every other lifecycle ⇒ all False. Set explicitly by the decision row.
- **Determinism:** reducer consumes only `reconciled_at IS NULL` facts, ordered `(observed_at, fact_id)`; expiry uses an injectable, recorded `now`; replay-from-scratch reproduces identical beliefs.
- **Docs:** ADR at `docs/adr/0001-belief-fact-contract-and-truth-maintenance.md`; design explainer `docs/design/TRUTH-MAINTENANCE.md`. Not added to published site nav → no `site/*.html` artifact.
- **Delivery:** build/verify in-tree, then stash-only-my-files → git worktree → feature branch → PR via `gh` (matching #112–#116). Local-green gated.

## Risk top 3

1. **Reducer determinism vs wall-clock** (expiry + "newer" comparison) — likelihood: med, mitigation: fixed `(observed_at, fact_id)` order, injectable+recorded `now`, belief stores authoritative source `observed_at`, stale facts recorded as conflicts not silently applied, replay-from-scratch equality test.
2. **Idempotency / double-processing** — likelihood: med, mitigation: `reconciled_at` watermark + partial unique active index `(subject,relation,scope) WHERE lifecycle='active'`; "reconcile twice" test asserts row counts unchanged.
3. **Surface collisions** (global `--json` vs `emit --json` payload; agent_id FK blocking external facts) — likelihood: low-med, mitigation: local `--json` value option for emit (+ stdin), nullable un-FK'd agent_id; both documented + tested.

## Phase map

| # | Phase | Depends on | Deliverable |
|---|-------|------------|-------------|
| 1 | ADR + schema + contract | — | ADR (14 answers) + `truth/{schema,contract}.py` + idempotent 4-table `ensure_truth` |
| 2 | Persistence: emit + queries | 1 | `TruthStore` with `emit_fact`, `list_beliefs`, `list_active_beliefs`, `get_fact`, `explain_belief` skeleton |
| 3 | Deterministic reducer | 1, 2 | `reconcile_beliefs` (Rules 1–9) + `quarantine_belief` (Rule 10) + admissibility + decisions |
| 4 | CLI `bene belief …` | 3 | 6 subcommands (emit/reconcile/ls/active/explain/quarantine) + `--json` |
| 5 | Docs + public API + fact catalog | 3, 4 | design doc, `__init__` exports, future-consumer fact catalogs, no-LLM test |
| 6 | Polish & Harden + Delivery | 1..5 | full suite green, ruff-clean files, hardening passes, worktree + PR |

---

## Phase 1 — ADR + schema + contract

**Why:** The contract and schema are the load-bearing foundation; an ADR forces every definitional question to be answered before code locks them in.

**Deliverables:**
- `docs/adr/0001-belief-fact-contract-and-truth-maintenance.md` (answers all 14 ADR questions)
- `bene/kernel/truth/__init__.py`
- `bene/kernel/truth/schema.py` (`TRUTH_SCHEMA_SQL`, `TRUTH_SCHEMA_VERSION`, `ensure_truth(conn)`)
- `bene/kernel/truth/contract.py` (Fact/Belief/Decision/Conflict dataclasses; `FACT_KINDS`, `BELIEF_LIFECYCLES`, `UNRELIABLE_SOURCE_TYPES`; validation; `value_hash`)
- `ensure_v2` calls `ensure_truth` (additive); `tests/kernel/test_truth.py` (schema tests)

**Acceptance criteria:**
- [ ] `ensure_truth(conn)` creates exactly `belief_facts`, `beliefs`, `belief_decisions`, `belief_conflicts`, `truth_schema_version` — verified by querying `sqlite_master`.
- [ ] `belief_facts` and `beliefs` have `subject`, `relation`, `scope`, `value`, `value_hash` as real columns (verified via `PRAGMA table_info`), not JSON-only.
- [ ] A partial unique index enforces one `active` belief per `(subject,relation,scope)` (verified via `sqlite_master` / index list).
- [ ] `ensure_truth` is idempotent: running twice leaves one `truth_schema_version` row and does not error.
- [ ] `ensure_v2(conn)` also creates the 4 truth tables (additive wiring) and still creates legacy v2 tables.
- [ ] `FACT_KINDS == {observation,claim,state,hypothesis,decision,policy}` and `BELIEF_LIFECYCLES == {candidate,active,superseded,quarantined,expired,rejected}`.
- [ ] `value_hash(1) == value_hash(1.0)` and `value_hash("a") != value_hash(1)` (canonical, via `genome_hash`).
- [ ] ADR file exists and contains a section answering each of the 14 required questions.
- [ ] No legacy table is ALTERed (grep diff: no `ALTER TABLE` against legacy tables).

**Mandatory commands:**
- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py`

**Evidence required:**
- pytest output showing schema tests pass + exit code
- `sqlite_master`/`PRAGMA` dump proving the 5 tables + columns + partial unique index
- `grep -c "^## " docs/adr/0001-*.md` (≥14 question sections) + the question list
- ruff exit codes

**Dependencies:** none

---

## Phase 2 — Persistence: emit + queries (TruthStore)

**Why:** Facts must be storable with every reconciliation-critical field intact before any reducer can reason over them; queries give the inspectable read surface.

**Deliverables:**
- `bene/kernel/truth/store.py` — `TruthStore(conn)`: `emit_fact(...)`, `get_fact(fact_id)`, `list_facts(...)`, `list_beliefs(...)`, `list_active_beliefs(...)`, `explain_belief(belief_id)` skeleton (belief + facts; decisions/conflicts filled in P3), plus internal belief/decision/conflict insert helpers.
- Module-level wrappers `emit_fact(conn, ...)`, `list_beliefs(conn, ...)`, `list_active_beliefs(conn, ...)` in `__init__.py`.
- Tests in `tests/kernel/test_truth.py` for emit + queries.

**Acceptance criteria:**
- [ ] `emit_fact` persists ALL reconciliation-critical fields (fact_id, kind, subject, relation, value, scope, source, source_type, confidence, observed_at, expires_at, run_id, agent_id, trace_id, evidence_uri, derived_from, metadata, value_hash, unsafe) — a direct-SQL read returns each non-null where supplied (Test 1).
- [ ] `emit_fact` computes and stores `value_hash` and defaults (`scope='global'`, `observed_at` set, `reconciled_at` NULL).
- [ ] `emit_fact` rejects an unknown `kind` with a clear error (validation).
- [ ] Emitting a `claim` fact creates a `belief_facts` row but **no** `beliefs` row (reducer hasn't run) (Test 2 precondition).
- [ ] `list_beliefs` / `list_active_beliefs` return inspectable dict/dataclass rows; empty DB returns `[]` (no crash).
- [ ] `explain_belief` on a missing id returns a clear empty/None result (no crash), and on a present belief returns belief + source facts.
- [ ] Direct-SQL test asserts `SELECT COUNT(*) FROM belief_facts` reflects emitted facts (Test 12 — SQLite inspectable).

**Mandatory commands:**
- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py`

**Evidence required:**
- pytest output (emit/query tests pass) + exit code
- a transcript dump of one emitted fact row read back via raw SQL showing all fields
- ruff exit codes

**Dependencies:** 1

---

## Phase 3 — Deterministic reducer + quarantine

**Why:** This is the core truth-maintenance engine: deterministic reconciliation, supersession, quarantine, expiry, admissibility, and a decision row for every transition.

**Deliverables:**
- `bene/kernel/truth/reducer.py` — `reconcile_beliefs(conn, *, now=None)` implementing Rules 1–9; `quarantine_belief(conn, belief_id, *, reason)` implementing Rule 10; admissibility computation (Rules 6/7); decision-write on every transition (Rule 8).
- `explain_belief` completed (belief + source facts + decisions + conflicts + admissibility flags).
- Module-level wrappers `reconcile_beliefs`, `quarantine_belief`, `explain_belief` exported.
- Tests in `tests/kernel/test_truth.py` covering Tests 3–11.

**Acceptance criteria:**
- [ ] Rule 1: a valid candidate fact with no active belief for its key creates exactly one `active` belief + a decision (Test 3).
- [ ] Rule 9 idempotency: running `reconcile_beliefs` twice over the same facts does not duplicate beliefs or decisions — belief/decision row counts identical after the 2nd run (Test 4).
- [ ] Rule 2: a newer same-key different-value fact moves the old belief to `superseded` (with `active_until` set) and creates a new `active` belief; both transitions have decisions; a `belief_conflicts` row records the contradiction (Test 5).
- [ ] Rule 3: a newer same-key same-value fact does NOT create a duplicate active belief (exactly one active remains) and links the fact (Test 6).
- [ ] Rule 4: a fact with `source_type` in `UNRELIABLE_SOURCE_TYPES` or `unsafe=1` produces a `quarantined` belief/candidate, never `active`, with a decision (Test 7).
- [ ] Rule 5: an expired fact (`expires_at` < `now`) does not create an `active` belief; the non-activation is explained by a decision row (Test 8).
- [ ] Rule 10: `quarantine_belief` moves an `active` belief to `quarantined`, sets admissibility all-False, and records a decision (Test 9).
- [ ] Rule 6: beliefs in `quarantined`/`superseded`/`expired`/`rejected` have `admissible_for_promotion = 0` (Test 10).
- [ ] Rule 7: an `active` reliable belief has admissibility flags set explicitly by its decision row (decision flags == belief flags) (admissibility test).
- [ ] Rule 8: every lifecycle transition has a corresponding `belief_decisions` row (no orphan transitions) (audited in tests).
- [ ] `explain_belief` returns belief, source facts, decisions, conflicts (if any), and admissibility flags (Test 11).
- [ ] Determinism/replay: reconciling the same fact set from a fresh DB twice yields identical belief `(subject,relation,scope,value,lifecycle)` tuples (replay test).
- [ ] Stale fact (older `observed_at` than active belief, different value) does NOT supersede; recorded as a conflict/no-op decision.

**Mandatory commands:**
- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py`

**Evidence required:**
- pytest output showing Tests 3–11 + replay + stale all pass + exit code
- a transcript excerpt of `explain_belief` output for a superseded key (belief + facts + decisions + conflict)
- ruff exit codes

**Dependencies:** 1, 2

---

## Phase 4 — CLI `bene belief …`

**Why:** The feature must be scriptable and honest from the command line, matching BENE's existing click + `--json` conventions.

**Deliverables:**
- `@cli.group("belief")` in `bene/cli/main.py` with subcommands: `emit` (`--json '{...}'` payload + stdin), `reconcile`, `ls`, `active`, `explain <belief_id>`, `quarantine <belief_id> --reason "..."`. Each calls `ensure_truth` + supports global `--json` output + `--db`.
- `tests/test_cli_belief.py` (CliRunner).

**Acceptance criteria:**
- [ ] `bene belief emit --json '{...}'` persists a fact and prints/returns its `fact_id`; reads from stdin when payload is `-` or omitted.
- [ ] `bene belief reconcile` runs the reducer and prints a summary (created/superseded/quarantined/refreshed counts); `--json` returns structured counts.
- [ ] `bene belief ls` lists beliefs; `bene belief active` lists only active beliefs; both honor `--json`.
- [ ] `bene belief explain <belief_id>` prints belief + facts + decisions + conflicts + admissibility; `--json` returns the structured object.
- [ ] `bene belief quarantine <belief_id> --reason "..."` quarantines and records a decision; reason appears in the decision.
- [ ] An end-to-end CliRunner test: emit → reconcile → active shows the belief → quarantine → active no longer shows it.
- [ ] `--json` output is valid JSON for every subcommand (parsed in tests).
- [ ] Unknown belief_id / malformed `--json` payload produce a clear non-crash error (exit code + message; `--json` error shape).

**Mandatory commands:**
- `uv run python -m pytest tests/test_cli_belief.py -v`
- `uv run ruff check bene/cli/main.py tests/test_cli_belief.py`
- `uv run ruff format --check tests/test_cli_belief.py`

**Evidence required:**
- pytest output (CLI tests pass) + exit code
- a real terminal run of the emit→reconcile→active→explain→quarantine sequence on a temp DB
- ruff exit codes (no NEW errors introduced in main.py vs baseline)

**Dependencies:** 3

---

## Phase 5 — Docs + public API + fact catalog

**Why:** The contract must be explained in BENE language and the public seam (API + future-consumer fact kinds) made explicit, without implementing consumer integrations yet.

**Deliverables:**
- `docs/design/TRUTH-MAINTENANCE.md` — engrams/facts/beliefs/decisions/admissibility in BENE language; explicit "this is NOT RAG / vector memory / a full expert system"; the agentdex-cli, eddie-agi-kb, and BENE fact catalogs; CLI + API usage.
- `bene/kernel/truth/__init__.py` exporting `emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief, TruthStore, ensure_truth` + constants.
- `tests/kernel/test_truth.py`: no-LLM/no-network/no-banned-dep source-scan test (Test 13) + public-import test.

**Acceptance criteria:**
- [ ] `from bene.kernel.truth import emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief` succeeds (import test).
- [ ] `docs/design/TRUTH-MAINTENANCE.md` contains the 5 BENE-language statements (engrams remember / facts structure / beliefs = current state / decisions explain / admissibility gates) and the "not RAG/vector/expert-system" disclaimer.
- [ ] The doc lists the agentdex-cli, eddie-agi-kb, and BENE fact catalogs (e.g. `baseline.status`, `paper.proposes.technique`, `tool_call.status`).
- [ ] Test 13: a source-scan over `bene/kernel/truth/` asserts no import of `litellm`, `openai`, `httpx`, `requests`, `socket`, CLIPS, graph/vector DB libs, and no thread/daemon spawn.
- [ ] `value_hash`/canonical reuse documented (provenance/lineage section).

**Mandatory commands:**
- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run python -c "from bene.kernel.truth import emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief, TruthStore, ensure_truth; print('ok')"`
- `uv run ruff check bene/kernel/truth/`

**Evidence required:**
- import command output (`ok`) + exit code
- pytest output (no-LLM + import tests pass)
- `grep` proof the doc contains the 5 statements + disclaimer + 3 fact catalogs

**Dependencies:** 3, 4

---

## Phase 6 — Polish & Harden + Delivery (worktree + PR)

**Why:** Catch what earlier phases missed (edge cases, determinism corners, stray debug), prove the whole suite is green, then land additively via a reviewable PR.

**Sub-passes (each must produce evidence):**

- [ ] **Edges** — empty inputs, missing optional fields, long/special-char subjects/values, multi-key isolation (facts for different keys don't cross-contaminate), bulk reconcile of many facts.
- [ ] **Determinism/idempotency re-proof** — replay-from-scratch equality + reconcile-twice no-op re-run as part of the full suite.
- [ ] **Security/safety** — validation on all emit inputs; quarantine/expiry/rejected truly non-admissible-for-promotion (the north-star invariant); no SQL injection (parameterized queries only — grep for f-string SQL).
- [ ] **Honesty** — CLI copy reads well, no debug placeholders, no work-trace/agent-session text in `docs/` (per repo doc policy).
- [ ] **Diff review** — `git diff` reviewed for stray `print`/debug, TODO/FIXME from this run, dead imports; clean.
- [ ] **Regression sweep** — full `pytest tests/` green (no NEW failures vs baseline) + my files ruff-clean.
- [ ] **Delivery** — stash-only-my-files → `git worktree` → feature branch → commit (Co-Authored-By trailer) → `gh pr create` (additive, body describes contract + rules + tests).

**Acceptance criteria:**
- [ ] Full suite: `uv run python -m pytest tests/ -q` shows 0 failed (or no NEW failures vs the pre-run baseline, with any pre-existing failures named).
- [ ] `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py` and `ruff format --check` on the same paths are clean.
- [ ] All parameterized SQL (no f-string-interpolated values in queries) — grep evidence.
- [ ] North-star invariant test: no `quarantined`/`superseded`/`expired`/`rejected` belief is ever `admissible_for_promotion=1` (asserted across all reducer tests).
- [ ] `git diff --stat` reviewed; no stray debug/TODO from this run.
- [ ] PR opened via `gh pr create` (capture URL) OR, if `gh` is unavailable, a feature branch with committed work + the exact `gh pr create` command printed.

**Mandatory commands:**
- `uv run python -m pytest tests/ -q`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py tests/test_cli_belief.py`

**Evidence required:**
- Full test summary (passed/failed counts) + exit code; pre-existing failures (if any) named and shown to pre-date this run
- ruff exit codes
- `git diff --stat` summary
- PR URL (or branch name + ready-to-run `gh pr create` command)

**Dependencies:** 1, 2, 3, 4, 5
