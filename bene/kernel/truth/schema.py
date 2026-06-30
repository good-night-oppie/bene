"""Truth-maintenance schema — additive, idempotent SQLite DDL.

Four tables plus a private version stamp, all ``CREATE ... IF NOT EXISTS``:

- ``belief_facts``     — structured claims derived from observations (immutable
                         once emitted; the reducer only sets ``reconciled_at``).
- ``beliefs``          — BENE's current accepted state, one ``active`` row per
                         ``(subject, relation, scope)`` (DB-enforced).
- ``belief_decisions`` — one row per lifecycle transition; every change is
                         explainable from here (Rule 8).
- ``belief_conflicts`` — same-key contradictions (supersession / stale / quarantine).

Contract (mirrors ``schema_v2.ensure_v2``): never ALTER legacy tables; all DDL
is ``IF NOT EXISTS``; ``ensure_truth`` is idempotent + concurrency-safe (the
version stamp is ``INSERT OR IGNORE`` so a racing duplicate is a clean no-op
instead of a UNIQUE-violation that aborts a writer mid-transaction).

Cross-references between the four tables are plain TEXT ids, NOT declared
``REFERENCES`` foreign keys. ``beliefs.last_decision_id`` ↔
``belief_decisions.belief_id`` is a genuine cycle; with ``PRAGMA foreign_keys=ON``
(set by ``Bene``) a declared FK pair would be unsatisfiable on insert. Referential
integrity is maintained by the deterministic reducer and asserted by tests. The
ONE hard DB-level invariant kept is the partial unique index guaranteeing a
single ``active`` belief per reconciliation key.
"""

from __future__ import annotations

import sqlite3

TRUTH_SCHEMA_VERSION = 1

TRUTH_SCHEMA_SQL = """
-- ============ FACTS (structured claims derived from observations) ============
CREATE TABLE IF NOT EXISTS belief_facts (
    fact_id        TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN
                   ('observation','claim','state','hypothesis','decision','policy')),
    subject        TEXT NOT NULL,
    relation       TEXT NOT NULL,
    value          TEXT,
    value_hash     TEXT NOT NULL,
    scope          TEXT NOT NULL DEFAULT 'global',
    source         TEXT,
    source_type    TEXT,
    confidence     REAL NOT NULL DEFAULT 1.0,
    observed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    expires_at     TEXT,
    run_id         TEXT,
    agent_id       TEXT,                     -- intentionally NO foreign key:
                                             -- facts may originate outside BENE agents
    trace_id       TEXT,
    evidence_uri   TEXT,
    derived_from   TEXT NOT NULL DEFAULT '[]',
    metadata       TEXT NOT NULL DEFAULT '{}',
    unsafe         INTEGER NOT NULL DEFAULT 0 CHECK (unsafe IN (0,1)),
    reconciled_at  TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_belief_facts_key
    ON belief_facts(subject, relation, scope);
CREATE INDEX IF NOT EXISTS idx_belief_facts_kind ON belief_facts(kind);
CREATE INDEX IF NOT EXISTS idx_belief_facts_source_type ON belief_facts(source_type);
CREATE INDEX IF NOT EXISTS idx_belief_facts_unreconciled
    ON belief_facts(observed_at, value_hash, fact_id) WHERE reconciled_at IS NULL;

-- ============ BELIEFS (current accepted state) ============
CREATE TABLE IF NOT EXISTS beliefs (
    belief_id                 TEXT PRIMARY KEY,
    subject                   TEXT NOT NULL,
    relation                  TEXT NOT NULL,
    value                     TEXT,
    value_hash                TEXT NOT NULL,
    scope                     TEXT NOT NULL DEFAULT 'global',
    lifecycle                 TEXT NOT NULL CHECK (lifecycle IN
                              ('candidate','active','superseded',
                               'quarantined','expired','rejected')),
    confidence                REAL NOT NULL DEFAULT 1.0,
    active_from               TEXT,
    active_until              TEXT,
    derived_from              TEXT NOT NULL DEFAULT '[]',
    last_decision_id          TEXT,
    admissible_for_context    INTEGER NOT NULL DEFAULT 0 CHECK (admissible_for_context IN (0,1)),
    admissible_for_promotion  INTEGER NOT NULL DEFAULT 0 CHECK (admissible_for_promotion IN (0,1)),
    admissible_for_action     INTEGER NOT NULL DEFAULT 0 CHECK (admissible_for_action IN (0,1)),
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    updated_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    -- North-star invariant, enforced at the DB level (not just in the reducer):
    -- a belief that is not currently ``active`` can never be admissible for
    -- anything. No raw SQL, migration, or future bug can promote an unsafe memory.
    CHECK (lifecycle = 'active' OR
           (admissible_for_context = 0 AND admissible_for_promotion = 0
            AND admissible_for_action = 0))
);
CREATE INDEX IF NOT EXISTS idx_beliefs_key ON beliefs(subject, relation, scope);
CREATE INDEX IF NOT EXISTS idx_beliefs_lifecycle ON beliefs(lifecycle);
-- The one hard DB-level invariant: at most one ACTIVE belief per reconciliation key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_beliefs_active_key
    ON beliefs(subject, relation, scope) WHERE lifecycle = 'active';

-- ============ DECISIONS (why a belief changed lifecycle — Rule 8) ============
CREATE TABLE IF NOT EXISTS belief_decisions (
    decision_id               TEXT PRIMARY KEY,
    belief_id                 TEXT,            -- NULL for no-op/rejected-fact decisions
    rule                      TEXT NOT NULL,
    from_lifecycle            TEXT,
    to_lifecycle              TEXT,
    reason                    TEXT NOT NULL DEFAULT '',
    fact_id                   TEXT,
    admissible_for_context    INTEGER NOT NULL DEFAULT 0,
    admissible_for_promotion  INTEGER NOT NULL DEFAULT 0,
    admissible_for_action     INTEGER NOT NULL DEFAULT 0,
    metadata                  TEXT NOT NULL DEFAULT '{}',
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_belief_decisions_belief ON belief_decisions(belief_id);
CREATE INDEX IF NOT EXISTS idx_belief_decisions_rule ON belief_decisions(rule);
CREATE INDEX IF NOT EXISTS idx_belief_decisions_fact ON belief_decisions(fact_id);

-- ============ CONFLICTS (same-key contradictions) ============
CREATE TABLE IF NOT EXISTS belief_conflicts (
    conflict_id   TEXT PRIMARY KEY,
    subject       TEXT NOT NULL,
    relation      TEXT NOT NULL,
    scope         TEXT NOT NULL DEFAULT 'global',
    belief_id     TEXT,
    fact_id       TEXT,
    kind          TEXT NOT NULL,
    resolution    TEXT NOT NULL DEFAULT 'pending',
    decision_id   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_belief_conflicts_key
    ON belief_conflicts(subject, relation, scope);

-- Truth-layer schema revision (separate from legacy + kernel version tables).
CREATE TABLE IF NOT EXISTS truth_schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
"""


def ensure_truth(conn: sqlite3.Connection) -> None:
    """Create the truth-maintenance tables if absent. Idempotent + concurrency-safe.

    Never touches legacy or kernel-v2 tables. Safe to call on every API/CLI entry.
    """
    conn.executescript(TRUTH_SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO truth_schema_version (version) VALUES (?)",
        (TRUTH_SCHEMA_VERSION,),
    )
    conn.commit()
