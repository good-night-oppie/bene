SUPERGOAL_PHASE_START
Phase: 3 of 6 — Deterministic reducer + quarantine
Task: Implement reconcile_beliefs (Rules 1–9) + quarantine_belief (Rule 10) + admissibility + decision-per-transition + complete explain_belief.
Type: brownfield · core-infra · kernel-feature
Mandatory commands: uv run python -m pytest tests/kernel/test_truth.py -v ; uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py ; uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py
Acceptance criteria: 13
Evidence required: pytest Tests 3–11+replay+stale output+exit; explain_belief dump for a superseded key; ruff exit codes
Depends on phases: 1, 2

## Why

This is the core truth-maintenance engine: deterministic reconciliation, supersession, quarantine, expiry, admissibility, and a decision row for every transition.

## Work

- `bene/kernel/truth/reducer.py`:
  - `reconcile_beliefs(conn, *, now=None) -> dict` — returns counts `{created, superseded, refreshed, quarantined, rejected, skipped}`.
    - `now` resolved once (DB now if None), recorded into decisions/`reconciled_at` for replay reproducibility.
    - Select unreconciled facts: `WHERE reconciled_at IS NULL ORDER BY observed_at, fact_id` (deterministic order). Process each in a transaction; set `reconciled_at = now` after.
    - Per fact, compute reliability: `unsafe==1` OR `source_type in UNRELIABLE_SOURCE_TYPES` → unreliable. Compute expiry: `expires_at` present and `< now` → expired.
    - **Rule 5 (expired):** do not create/activate. If no active belief exists, write a decision (belief_id NULL, rule=`rule_5_expired`, to_lifecycle=`expired`/none, reason). Count `rejected`/`skipped`.
    - **Rule 4 (unreliable/unsafe):** create or move into `quarantined` (NOT active). Decision rule=`rule_4_quarantine`, admissibility all 0. If an active belief for the key exists, leave it (do not let an unreliable fact supersede a good active belief); record the quarantined candidate + a conflict row. Count `quarantined`.
    - Look up current `active` belief for `(subject,relation,scope)`:
      - **Rule 1 (none):** insert `active` belief (active_from = fact.observed_at), decision rule=`rule_1_create` (candidate→active or none→active), admissibility = reliable-active policy (context/promotion/action all 1). derived_from=[fact_id]. Count `created`.
      - **Rule 3 (same value_hash, fact newer-or-equal):** do NOT create a new belief; append fact_id to belief.derived_from, bump updated_at, optionally raise confidence; decision rule=`rule_3_refresh` (active→active, link). Count `refreshed`.
      - **Rule 2 (different value_hash, fact.observed_at > belief.active_from):** transition old belief → `superseded` (active_until=now) + decision rule=`rule_2_supersede` (active→superseded); insert new `active` belief + decision rule=`rule_2_supersede` (none→active); insert `belief_conflicts` row (kind=`same_key_different_value`, resolution=`superseded`). Count `superseded`.
      - **Stale (different value but fact.observed_at <= belief.active_from):** do NOT supersede; insert conflict (kind=`stale_value`, resolution=`ignored`) + decision (belief_id=active, rule=`rule_2_stale_ignored`, from==to==active). Count `skipped`.
  - `quarantine_belief(conn, belief_id, *, reason) -> dict` — **Rule 10:** move belief to `quarantined`, active_until=now, admissibility all 0, decision rule=`rule_10_manual_quarantine` (prev→quarantined, reason). Overrides active. Idempotent-safe (already quarantined → no duplicate decision, return status).
  - Admissibility policy (Rules 6/7) as a documented pure function `admissibility_for(lifecycle, *, reliable, expired)`: active+reliable+not-expired ⇒ (1,1,1); everything else ⇒ (0,0,0). The DECISION row stores the trio explicitly; the belief mirrors it. Rule 6 guaranteed: non-active never gets promotion=1.
  - Every lifecycle transition writes a `belief_decisions` row (Rule 8). Use TruthStore insert helpers from P2.
- Complete `TruthStore.explain_belief`: belief + source facts (derived_from + key match) + ALL decisions (ordered) + conflicts (key match) + admissibility flags.
- Export `reconcile_beliefs`, `quarantine_belief`, `explain_belief` module-level wrappers in `__init__.py`.
- Extend `tests/kernel/test_truth.py` with Tests 3–11 + replay + stale + idempotency.

## Acceptance criteria (all must pass — verify each in transcript)

- Rule 1: valid candidate fact, no active belief → exactly one `active` belief + decision (Test 3).
- Rule 9: `reconcile_beliefs` twice over same facts → identical belief AND decision row counts (idempotent) (Test 4).
- Rule 2: newer same-key different-value fact → old belief `superseded` (active_until set) + new `active` belief; both have decisions; a `belief_conflicts` row exists (Test 5).
- Rule 3: newer same-key same-value fact → still exactly one active belief (no duplicate), fact linked (Test 6).
- Rule 4: `source_type` unreliable OR `unsafe=1` → `quarantined`, never `active`, with a decision (Test 7).
- Rule 5: expired fact (`expires_at < now`) → no `active` belief; non-activation explained by a decision row (Test 8).
- Rule 10: `quarantine_belief` on an active belief → `quarantined`, admissibility all 0, decision with the reason (Test 9).
- Rule 6: `quarantined`/`superseded`/`expired`/`rejected` beliefs all have `admissible_for_promotion = 0` (Test 10).
- Rule 7: `active` reliable belief admissibility flags equal its decision row's flags (explicitly set) (admissibility test).
- Rule 8: every lifecycle transition has a `belief_decisions` row (no orphan transitions) (audited in tests).
- `explain_belief` returns belief + source facts + decisions + conflicts + admissibility (Test 11).
- Replay: reconciling the same fact set from a fresh DB twice yields identical `(subject,relation,scope,value,lifecycle)` tuples.
- Stale: an older-than-active different-value fact does NOT supersede; recorded as conflict + no-op decision.

## Mandatory commands (run each, surface last ~10 lines + exit code)

- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run ruff check bene/kernel/truth/ tests/kernel/test_truth.py`
- `uv run ruff format --check bene/kernel/truth/ tests/kernel/test_truth.py`

## Evidence required in transcript

- pytest output showing Tests 3–11 + replay + stale + idempotency all pass + exit code
- a transcript excerpt of `explain_belief` output for a superseded key (belief + facts + decisions + conflict)
- ruff check + format exit codes

## Notes

Determinism is the whole point: fixed `(observed_at, fact_id)` ordering, `now` resolved once and recorded, belief stores authoritative `active_from`. Never let an unreliable/stale/expired fact mutate a good active belief. All transitions in transactions. Parameterized SQL only. The partial unique active index will REJECT a second active belief for a key — rely on it as a backstop (transition old → superseded BEFORE inserting new active).
