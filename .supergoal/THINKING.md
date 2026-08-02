# THINKING — BENE Truth Maintenance layer

## Goals
- Deterministic, SQLite-backed **Belief/Fact contract + reducer** that separates: raw engrams (permanent) → **facts** (structured claims) → **beliefs** (current accepted state) → **decisions** (why lifecycle changed) → **admissibility** (safe for context / promotion / action).
- Small, boring, auditable, **additive**. Kernel feature, not AI feature.
- 100% explainable belief transitions; idempotent + replayable single-node reducer.
- North star: BENE must never let future agents evolve from unsafe memories.

## Constraints (hard)
- No CLIPS, graph DB, vector DB, Postgres, Django, background daemons, **no LLM calls**, no network. Stdlib `sqlite3`/`json`/`hashlib` + `ulid` only.
- Never ALTER legacy tables. All new DDL `IF NOT EXISTS`, idempotent ensure. Preserve existing APIs.
- bene-main is a shared multi-writer checkout → build/verify in-tree, deliver via worktree + PR.
- Keep MY files ruff-clean; gate on local green (repo CI is structurally red on ruff drift — not mine).

## Design decisions
- **Home:** new subpackage `bene/kernel/truth/` (mirrors `eval/`, `memory/`): `schema.py`, `contract.py`, `store.py`, `reducer.py`, `__init__.py`. Reuse `(conn, store)` ctor style; module-level public API wrappers.
- **4 tables** (`belief_facts`, `beliefs`, `belief_decisions`, `belief_conflicts`) via `ensure_truth(conn)` — own `truth_schema_version` table, `INSERT OR IGNORE`, idempotent + concurrency-safe (copying `ensure_v2`'s rationale). Also call `ensure_truth` from `ensure_v2` so kernel-attached DBs get it; CLI/API call it directly so it works standalone.
- **Reconciliation key:** `(subject, relation, scope)` as real indexed columns (never JSON). `value` + canonical `value_hash` are real columns too.
- **Single-active invariant** enforced at DB level: `CREATE UNIQUE INDEX ... ON beliefs(subject,relation,scope) WHERE lifecycle='active'`. One current belief per key, by construction.
- **Value equality** via `bene/kernel/genome_canonical.py` (int==float, NFC==NFD, CRLF==LF; num≠str) → deterministic `value_hash`. Rule 2 (different value → supersede) vs Rule 3 (same value → refresh) is canonical, not naive string compare.
- **agent_id is nullable, NO hard FK** on `belief_facts` — facts originate outside BENE agents (agentdex-cli, eddie-agi-kb, external imports). Documented in ADR §scope.
- **Determinism mechanics:** reducer consumes only unreconciled facts (`reconciled_at IS NULL`), ordered `ORDER BY observed_at, fact_id`; pure rule functions; expiry compared against an **injectable `now` reference** recorded per reconcile so replay is reproducible. Belief stores its authoritative source `observed_at` (= `active_from`) so "newer" is an explicit comparison; **stale** facts (older than active) are recorded as conflicts, never silently applied.
- **Admissibility (Rules 6/7):** decision row explicitly stores `admissible_for_{context,promotion,action}`; belief mirrors them. Active + reliable + not-expired ⇒ all three True; candidate/quarantined/expired/rejected/superseded ⇒ all False (Rule 6). Every transition writes a decision (Rule 8); `belief_id` nullable on decisions so a rejected/expired no-op fact is still explainable.
- **Reliability policy (Rule 4):** deterministic, documented sets — `UNRELIABLE_SOURCE_TYPES = {failed, unreliable, untrusted, error}` plus explicit `unsafe=1` → quarantine path; unknown source_types default reliable (so future consumers work without edits).
- **CLI `--json` duality:** global `--json` is the output flag (`bene --json belief active`); `belief emit` takes its fact payload via a local `--json TEXT` option (+ stdin fallback). Different parser levels → no click conflict. Documented.
- **Docs home:** ADR at `docs/adr/0001-belief-fact-contract-and-truth-maintenance.md`; design explainer at `docs/design/TRUTH-MAINTENANCE.md`. Neither is in the published mkdocs/site nav → no `site/*.html` artifact needed (avoids the site-rebuild rabbit hole).

## Risks (top 3)
1. **Determinism vs wall-clock** (expiry + "newer"). Mitigation: fixed order, injectable+recorded `now`, stored source `observed_at`, explicit stale handling, replay-from-scratch equality test.
2. **Idempotency / double counting.** Mitigation: `reconciled_at` watermark + partial unique active index; "reconcile twice" test asserts unchanged row counts.
3. **Surface collisions** — `--json` global-vs-emit, agent_id FK blocking external facts. Mitigation: local `--json` value option for emit; nullable un-FK'd agent_id; both documented + tested.

## Dependencies / ordering
schema/contract → store/emit → reducer → CLI → docs/exports → polish+delivery. Tests folded into each phase (pass at that phase = independently shippable).

## Memory hits applied
See `applied-memories.md`: worktree-PR delivery, ruff-local-green gating, genome-canonical reuse, re-run final suite in foreground, final gate = suite+ruff.

## Tools relied on
Repo conventions + Python stdlib + `ulid` + `genome_canonical`. No web/Context7 needed (deterministic internal feature). Optional adversarial review via `pal`/self-review in Polish.

## Best practices applied
Additive migration (IF NOT EXISTS + version stamp), DB-enforced invariants (partial unique index), decision-per-transition audit trail, canonical hashing for equality, injectable clock for replay, source-scan test to prove no banned deps.
