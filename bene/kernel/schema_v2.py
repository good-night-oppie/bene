"""BENE 2.0 kernel schema — additive v2 tables.

Contract (docs/design/KERNEL-SPEC.md §1): never ALTER legacy tables; all v2
DDL is ``IF NOT EXISTS``; ``ensure_v2`` is idempotent. The v2 revision is
tracked in a dedicated ``kernel_schema_version`` table (the legacy
``schema_version`` table has no component column and is left untouched).
"""

from __future__ import annotations

import sqlite3

KERNEL_SCHEMA_VERSION = 1

SCHEMA_V2_SQL = """
-- ============ ENGRAM SUBSTRATE ============
CREATE TABLE IF NOT EXISTS engrams (
    engram_id     TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN
                  ('trace','episodic','semantic','procedural','strategic',
                   'eval','experiment','trust','pollution','intervention',
                   'proposal','spec','report')),
    tier          INTEGER NOT NULL DEFAULT 0 CHECK (tier BETWEEN 0 AND 4),
    title         TEXT NOT NULL,
    content_hash  TEXT,
    inline_body   TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}',
    provenance    TEXT NOT NULL,
    agent_id      TEXT REFERENCES agents(agent_id),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    superseded_by TEXT REFERENCES engrams(engram_id)
);
CREATE INDEX IF NOT EXISTS idx_engrams_kind   ON engrams(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_agent  ON engrams(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_tier   ON engrams(tier);
CREATE INDEX IF NOT EXISTS idx_engrams_active ON engrams(kind) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS engram_links (
    link_id     TEXT PRIMARY KEY,
    src_id      TEXT NOT NULL REFERENCES engrams(engram_id),
    dst_id      TEXT NOT NULL REFERENCES engrams(engram_id),
    link_type   TEXT NOT NULL CHECK (link_type IN
                ('derived_from','consolidates','verifies','refutes','associates',
                 'supersedes','about_agent','gated_by')),
    weight      REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    UNIQUE(src_id, dst_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_src ON engram_links(src_id);
CREATE INDEX IF NOT EXISTS idx_links_dst ON engram_links(dst_id);

CREATE VIRTUAL TABLE IF NOT EXISTS engram_fts USING fts5(
    engram_id UNINDEXED, title, body, tokenize='porter'
);

-- ============ CAPABILITIES & AUTONOMY ============
CREATE TABLE IF NOT EXISTS capabilities (
    name            TEXT PRIMARY KEY,
    description     TEXT NOT NULL,
    autonomy_level  INTEGER NOT NULL CHECK (autonomy_level BETWEEN 0 AND 4),
    handler_ref     TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE TABLE IF NOT EXISTS autonomy_grants (
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    domain      TEXT NOT NULL DEFAULT '*',
    level       INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
    granted_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    revoked_at  TEXT,
    PRIMARY KEY (agent_id, domain)
);

-- ============ EVAL REGISTRY (thin; verdicts live as engrams) ============
CREATE TABLE IF NOT EXISTS probe_registry (
    probe_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    gate_spec     TEXT NOT NULL,
    lock_sha256   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'registered'
                  CHECK (status IN ('registered','admissible','inadmissible','retired')),
    subject_ref   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id         TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('probe','evolution','consolidation','sweep')),
    probe_id       TEXT REFERENCES probe_registry(probe_id),
    verdict_engram TEXT REFERENCES engrams(engram_id),
    summary        TEXT NOT NULL DEFAULT '',
    metrics        TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_experiments_kind ON experiment_runs(kind, created_at);

-- Kernel schema revision (separate from legacy schema_version — never touched)
CREATE TABLE IF NOT EXISTS kernel_schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
"""


def ensure_v2(conn: sqlite3.Connection) -> None:
    """Create v2 tables if absent. Idempotent + concurrency-safe; never touches
    legacy tables.

    The version stamp is a single ``INSERT OR IGNORE`` rather than a
    check-then-insert: two connections calling ``ensure_v2`` on a fresh db would
    both read an empty ``kernel_schema_version`` and both INSERT the same version,
    and the loser's UNIQUE violation aborts its transaction mid-flight — leaving
    the write lock held until the other writer blocks out its full ``busy_timeout``
    ("database is locked"). OR IGNORE makes the racing duplicate a clean no-op.
    """
    conn.executescript(SCHEMA_V2_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO kernel_schema_version (version) VALUES (?)",
        (KERNEL_SCHEMA_VERSION,),
    )
    conn.commit()
