# Inside bene.db

Open `bene.db` with any SQLite client and you can answer, in plain SQL, every question your agents can raise: what they did, what they wrote, what they remember, and where you can roll them back to. This page maps each of the 11 tables to the question it answers, documents every column, and hands you queries ready to paste.

> **The entire state of your agent fleet is one SQLite file — query it, `cp` it, back it up; nothing leaves your machine.**

The schema is at version **7**, defined in `bene/schema.py`.

---

<a id="overview"></a>

## One file, eleven tables

bene keeps everything in a single SQLite database opened in WAL (Write-Ahead Logging) mode. Several tables hang off `agents` (`files`, `events`, `tool_calls`, `state`, `checkpoints`, `memory`, `agent_skills`); `blobs` holds the bytes that `files` points at. `shared_log` records coordination events on the A2A bus (`shared_log.agent_id` contains the base agent name but has no foreign key constraint to `agents`):

```text
agents  ----<  files         (1:N - each agent has many files)
        ----<  tool_calls    (1:N - each agent has many tool calls)
        ----<  state         (1:N - each agent has many KV pairs)
        ----<  events        (1:N - each agent has many events)
        ----<  checkpoints   (1:N - each agent has many checkpoints)

blobs   <----  files         (1:N - many files can share one blob)
```

Two conventions hold everywhere:

- **Timestamps** are ISO 8601 text at millisecond precision, produced by `strftime('%Y-%m-%dT%H:%M:%f', 'now')`.
- **JSON columns** — `config`, `metadata`, `input`, `output`, `payload`, `value`, `file_manifest`, `state_snapshot` — always contain valid JSON text.

---

## Pick your question

| If you're asking… | Read |
|---|---|
| What did this agent actually do? | [events](#events) |
| Which tools ran, with what input and timing? | [tool_calls](#tool_calls-every-tool-invocation) |
| Which agents exist, and are they alive? | [agents](#agents-the-roster) |
| What is an agent's current working state (short-term scratch)? | [state](#state-per-agent-key-value-memory) |
| What does an agent durably remember / recall across sessions? | `memory` + `memory_fts` — full-text searchable (`SELECT … FROM memory_fts WHERE memory_fts MATCH '…'`); see [memory.md](memory.md) |
| Where can I roll back to? | [checkpoints](#checkpoints-snapshots-you-can-return-to) |
| What has an agent written? | [files](#files-the-virtual-filesystem) |
| How are the bytes actually stored? | [blobs](#blobs-deduplicated-content) |
| Which migrations has this file seen? | [schema_version](#schema_version-the-migration-record) |

---

## events

bene's audit trail. Every move an agent makes — file writes, tool calls, lifecycle transitions, checkpoints — is appended here and never rewritten, so the journal you query is exactly what happened.

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    idempotency_key TEXT
);
-- schema v4 also adds a partial unique index for safe (Temporal) retries:
-- CREATE UNIQUE INDEX idx_events_idem ON events(agent_id, idempotency_key)
--   WHERE idempotency_key IS NOT NULL;
-- The same `idempotency_key TEXT` column + partial unique index exist on `tool_calls` and `files`.
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `event_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Rises monotonically, so it doubles as a global ordering. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | The agent behind the event. |
| `event_type` | TEXT | NOT NULL | One of the strings catalogued below. |
| `payload` | TEXT | NOT NULL, default `'{}'` | Event-specific detail as a JSON object. |
| `timestamp` | TEXT | NOT NULL, auto-generated | ISO 8601, millisecond precision, written automatically. |
| `idempotency_key` | TEXT | nullable, unique per agent when set (v4) | A replayed write with the same key is a no-op instead of a duplicate — enables safe Temporal activity retries. Also on `tool_calls` and `files`. |

### Event types

The standard `event_type`s bene emits, with the payload shape each carries (the Temporal runtime emits a few additional types):

| Event Type | Payload Example | Trigger |
|---|---|---|
| `agent_spawn` | `{"name": "...", "parent_id": null, "config": {...}}` | Agent created via `spawn()` |
| `agent_pause` | `{}` | Agent paused |
| `agent_resume` | `{}` | Agent resumed |
| `agent_kill` | `{}` | Agent killed |
| `agent_complete` | `{}` | Agent completed successfully |
| `agent_fail` | `{"error": "..."}` | Agent failed |
| `state_change` | `{"field": "status", "from": "initialized", "to": "running"}` | Status transition |
| `file_read` | `{"path": "/src/app.py"}` | File read from VFS |
| `file_write` | `{"path": "/src/app.py", "size": 1234, "version": 2}` | File written to VFS |
| `file_delete` | `{"path": "/tmp/scratch.txt"}` | File deleted from VFS |
| `tool_call_start` | `{"call_id": "...", "tool_name": "fs_read"}` | Tool execution started |
| `tool_call_end` | `{"call_id": "...", "status": "success"}` | Tool execution completed |
| `llm_call` | `{"model": "...", "prompt_len": 1234, "input_tokens": 800, "output_tokens": 120, "cache_read_tokens": 0, "cache_creation_tokens": 0}` | Model call completed (Temporal runtime only) |
| `checkpoint_create` | `{"checkpoint_id": "...", "label": "pre-refactor"}` | Checkpoint created |
| `checkpoint_restore` | `{"checkpoint_id": "..."}` | Checkpoint restored |
| `error` | `{"message": "..."}` | Runtime error |
| `warning` | `{"message": "..."}` | Runtime warning |

### Paste-ready queries

```sql
-- Full timeline for an agent
SELECT event_id, event_type, payload, timestamp
FROM events
WHERE agent_id = '01HXYZ...'
ORDER BY event_id;

-- What did an agent do in the last hour?
SELECT event_type, payload, timestamp
FROM events
WHERE agent_id = '01HXYZ...'
AND timestamp > strftime('%Y-%m-%dT%H:%M:%f', 'now', '-1 hour')
ORDER BY event_id;

-- Count events by type for an agent
SELECT event_type, COUNT(*) as count
FROM events
WHERE agent_id = '01HXYZ...'
GROUP BY event_type
ORDER BY count DESC;

-- System-wide activity summary
SELECT event_type, COUNT(*) as count
FROM events
GROUP BY event_type
ORDER BY count DESC;

-- Find all file writes across all agents
SELECT e.agent_id, a.name,
       json_extract(e.payload, '$.path') as file_path,
       json_extract(e.payload, '$.size') as size,
       e.timestamp
FROM events e
JOIN agents a ON e.agent_id = a.agent_id
WHERE e.event_type = 'file_write'
ORDER BY e.timestamp DESC
LIMIT 20;
```

*Indexed by `idx_events_agent_time` (`agent_id, timestamp`) and `idx_events_type` (`event_type`) — see the [index catalog](#index-catalog).*

---

## tool_calls: every tool invocation

Each tool an agent runs is journaled with its input, output, timing, and token spend — so a slow or failing run can be traced call by call, and nested calls reconstructed as a chain.

```sql
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id         TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    tool_name       TEXT NOT NULL,
    input           TEXT NOT NULL,
    output          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','success','error','timeout')),
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    completed_at    TEXT,
    duration_ms     INTEGER,
    token_count     INTEGER,
    cost_usd        REAL DEFAULT 0.0,
    parent_call_id  TEXT REFERENCES tool_calls(call_id),
    error_message   TEXT
);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `call_id` | TEXT | PRIMARY KEY | ULID, unique per invocation. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | The calling agent. |
| `tool_name` | TEXT | NOT NULL | Which tool ran (e.g., `fs_read`, `shell_exec`, `fs_write`). |
| `input` | TEXT | NOT NULL | Arguments, serialized as JSON. |
| `output` | TEXT | nullable | Result as JSON; stays NULL until the call finishes. |
| `status` | TEXT | NOT NULL, CHECK constraint | One of `pending`, `running`, `success`, `error`, `timeout`. |
| `started_at` | TEXT | NOT NULL, auto-generated | Set when the call is logged. |
| `completed_at` | TEXT | nullable | Filled in at finish time. |
| `duration_ms` | INTEGER | nullable | Wall-clock milliseconds, computed on completion. |
| `token_count` | INTEGER | nullable | Tokens consumed by the model call that triggered this tool use. |
| `cost_usd` | REAL | default 0.0 | USD estimate; reserved for future use. |
| `parent_call_id` | TEXT | FK -> tool_calls(call_id), nullable | Points at the parent call, so nested calls form a traceable chain. |
| `error_message` | TEXT | nullable | Populated when status is `error`. |

### Paste-ready queries

```sql
-- Recent tool calls for an agent
SELECT call_id, tool_name, status, duration_ms, token_count
FROM tool_calls
WHERE agent_id = '01HXYZ...'
ORDER BY started_at DESC
LIMIT 20;

-- Token consumption by agent
SELECT a.name, SUM(tc.token_count) as total_tokens, COUNT(*) as calls
FROM tool_calls tc
JOIN agents a ON tc.agent_id = a.agent_id
WHERE tc.status = 'success'
GROUP BY tc.agent_id
ORDER BY total_tokens DESC;

-- Failed tool calls with error details
SELECT agent_id, tool_name, error_message, started_at
FROM tool_calls
WHERE status = 'error'
ORDER BY started_at DESC;

-- Average duration per tool type
SELECT tool_name, AVG(duration_ms) as avg_ms, COUNT(*) as calls
FROM tool_calls
WHERE status = 'success'
GROUP BY tool_name
ORDER BY avg_ms DESC;

-- Trace a tool call chain (recursive CTE)
WITH RECURSIVE chain AS (
    SELECT call_id, tool_name, parent_call_id, 0 as depth
    FROM tool_calls WHERE call_id = 'target-call-id'
    UNION ALL
    SELECT tc.call_id, tc.tool_name, tc.parent_call_id, c.depth + 1
    FROM tool_calls tc JOIN chain c ON tc.parent_call_id = c.call_id
)
SELECT * FROM chain ORDER BY depth;
```

*Indexed by `idx_tool_calls_agent` (`agent_id, started_at`), `idx_tool_calls_tool` (`tool_name`), and `idx_tool_calls_status` (`status`) — see the [index catalog](#index-catalog).*

---

## agents: the roster

One row per agent: who exists, who spawned whom, and which lifecycle state each one is in right now.

```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_id       TEXT REFERENCES agents(agent_id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    status          TEXT NOT NULL DEFAULT 'initialized'
                    CHECK (status IN ('initialized','running','paused','completed','failed','killed')),
    config          TEXT NOT NULL DEFAULT '{}',
    metadata        TEXT NOT NULL DEFAULT '{}',
    pid             INTEGER,
    last_heartbeat  TEXT
);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_id);
CREATE INDEX IF NOT EXISTS idx_agents_created_at ON agents(created_at);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `agent_id` | TEXT | PRIMARY KEY | ULID — unique and sortable by creation time. |
| `name` | TEXT | NOT NULL | A label you choose (e.g., "test-writer"). |
| `parent_id` | TEXT | FK -> agents(agent_id), nullable | Set when another agent spawned this one; NULL at the root. |
| `created_at` | TEXT | NOT NULL, auto-generated | Stamped at spawn, ISO 8601. |
| `status` | TEXT | NOT NULL, CHECK constraint | One of `initialized`, `running`, `paused`, `completed`, `failed`, `killed`. |
| `config` | TEXT | NOT NULL, default `'{}'` | JSON settings for the agent (e.g., `{"force_model": "deepseek-r1-70b"}`). |
| `metadata` | TEXT | NOT NULL, default `'{}'` | Free-form JSON, yours to fill. |
| `pid` | INTEGER | nullable | OS process ID while the agent runs. |
| `last_heartbeat` | TEXT | nullable | Most recent heartbeat, ISO 8601. |

### Paste-ready queries

```sql
-- List all running agents
SELECT agent_id, name, last_heartbeat
FROM agents WHERE status = 'running';

-- Find agents spawned by a parent
SELECT agent_id, name, status
FROM agents WHERE parent_id = '01HXYZ...';

-- Agent lifecycle summary
SELECT status, COUNT(*) as count
FROM agents GROUP BY status;

-- Find stale agents (no heartbeat in 5 minutes)
SELECT agent_id, name, last_heartbeat
FROM agents
WHERE status = 'running'
AND last_heartbeat < strftime('%Y-%m-%dT%H:%M:%f', 'now', '-5 minutes');
```

*Indexed by `idx_agents_status` (`status`) and `idx_agents_parent` (`parent_id`) — see the [index catalog](#index-catalog).*

---

## state: per-agent key-value memory

What an agent currently knows, as queryable rows: each agent gets its own key-value namespace, and any JSON-serializable value fits.

```sql
CREATE TABLE IF NOT EXISTS state (
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (agent_id, key)
);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `agent_id` | TEXT | NOT NULL, FK -> agents, part of PK | Owner — first half of the primary key. |
| `key` | TEXT | NOT NULL, part of PK | Entry name (e.g., `conversation`, `iteration`, `progress`). |
| `value` | TEXT | NOT NULL | JSON text: string, number, array, or object. |
| `updated_at` | TEXT | NOT NULL, auto-generated | Refreshed on every write. |

### Behavior notes

- The composite primary key `(agent_id, key)` keeps keys unique per agent and is what makes `ON CONFLICT` upserts possible.
- `set_state()` runs `INSERT ... ON CONFLICT DO UPDATE`, so re-setting an existing key swaps in the new value atomically.
- The CCR loop persists `conversation`, `iteration`, `task`, and `result` here — which puts an agent's entire conversation history one SELECT away.

### Paste-ready queries

```sql
-- Get all state for an agent
SELECT key, value, updated_at
FROM state
WHERE agent_id = '01HXYZ...'
ORDER BY key;

-- Get a specific state value
SELECT value FROM state
WHERE agent_id = '01HXYZ...' AND key = 'iteration';

-- Find agents at a specific iteration
SELECT s.agent_id, a.name, s.value as iteration
FROM state s
JOIN agents a ON s.agent_id = a.agent_id
WHERE s.key = 'iteration'
ORDER BY CAST(s.value AS INTEGER) DESC;

-- State key usage across all agents
SELECT key, COUNT(*) as agent_count
FROM state
GROUP BY key
ORDER BY agent_count DESC;
```

---

## checkpoints: snapshots you can return to

A checkpoint freezes an agent's files and state at one moment, so a bad turn never has to be permanent: restore, diff, and keep going.

```sql
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id   TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    label           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    event_id        INTEGER REFERENCES events(event_id),
    file_manifest   TEXT NOT NULL,
    state_snapshot  TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}'
);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `checkpoint_id` | TEXT | PRIMARY KEY | ULID. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | Whose snapshot this is. |
| `label` | TEXT | nullable | Optional tag (e.g., `"pre-refactor"`, `"auto-iter-10"`). |
| `created_at` | TEXT | NOT NULL, auto-generated | Stamped at creation, ISO 8601. |
| `event_id` | INTEGER | FK -> events(event_id), nullable | Watermark into the event stream at snapshot time; diffs anchor on it. |
| `file_manifest` | TEXT | NOT NULL | JSON array of file entries: `[{"path": "...", "content_hash": "...", "version": N}, ...]`. |
| `state_snapshot` | TEXT | NOT NULL | Every KV pair at snapshot time: `{"key1": value1, "key2": value2, ...}`. |
| `metadata` | TEXT | NOT NULL, default `'{}'` | Extra JSON, yours to use. |

### Paste-ready queries

```sql
-- List checkpoints for an agent
SELECT checkpoint_id, label, created_at, event_id
FROM checkpoints
WHERE agent_id = '01HXYZ...'
ORDER BY created_at;

-- Get checkpoint details (file count, state key count)
SELECT
    checkpoint_id,
    label,
    created_at,
    json_array_length(file_manifest) as file_count,
    (SELECT count(*) FROM json_each(state_snapshot)) as state_keys
FROM checkpoints
WHERE agent_id = '01HXYZ...';

-- Find auto-checkpoints
SELECT checkpoint_id, label, created_at
FROM checkpoints
WHERE label LIKE 'auto-iter-%'
ORDER BY created_at;

-- Inspect a checkpoint's file manifest
SELECT
    json_extract(value, '$.path') as path,
    json_extract(value, '$.content_hash') as hash,
    json_extract(value, '$.version') as version
FROM checkpoints, json_each(file_manifest)
WHERE checkpoint_id = '01HABC...';
```

*Indexed by `idx_checkpoints_agent` (`agent_id, created_at`) — see the [index catalog](#index-catalog).*

---

## files: the virtual filesystem

Every write an agent makes becomes a new versioned row inside that agent's own namespace — earlier versions stay queryable, and a soft delete hides a path without destroying its history.

```sql
CREATE TABLE IF NOT EXISTS files (
    file_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    path            TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT,
    size            INTEGER NOT NULL DEFAULT 0,
    mode            INTEGER NOT NULL DEFAULT 33188,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    modified_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    version         INTEGER NOT NULL DEFAULT 1,
    deleted         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(agent_id, path, version)
);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `file_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Internal row id. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | Namespace owner; every lookup filters on it. |
| `path` | TEXT | NOT NULL | Absolute and POSIX-normalized (e.g., `/src/main.py`). |
| `is_dir` | INTEGER | NOT NULL, default 0 | 1 marks a directory. |
| `content_hash` | TEXT | nullable | SHA-256 key into `blobs`; NULL for directories. |
| `size` | INTEGER | NOT NULL, default 0 | Bytes before compression. |
| `mode` | INTEGER | NOT NULL, default 33188 | Unix mode; 33188 = `0o100644` (regular file, rw-r--r--). |
| `created_at` | TEXT | NOT NULL, auto-generated | When this version appeared. |
| `modified_at` | TEXT | NOT NULL, auto-generated | Last touch. |
| `version` | INTEGER | NOT NULL, default 1 | Bumped on every write to the same path. |
| `deleted` | INTEGER | NOT NULL, default 0 | 1 = soft-deleted: hidden from listings, kept for history and checkpoint restore. |

The constraint `UNIQUE(agent_id, path, version)` keeps versions distinct — one row per agent, per path, per version number.

### Paste-ready queries

```sql
-- List all active files for an agent
SELECT path, size, version, modified_at
FROM files
WHERE agent_id = '01HXYZ...' AND deleted = 0 AND is_dir = 0
ORDER BY path;

-- Get file version history
SELECT version, content_hash, size, created_at, deleted
FROM files
WHERE agent_id = '01HXYZ...' AND path = '/src/app.py'
ORDER BY version;

-- List directory contents (one level deep)
SELECT path, is_dir, size, modified_at
FROM files
WHERE agent_id = '01HXYZ...'
AND deleted = 0
AND path LIKE '/src/%'
AND path NOT LIKE '/src/%/%'
AND path != '/src';

-- Total storage used per agent
SELECT agent_id, SUM(size) as total_bytes, COUNT(*) as file_count
FROM files
WHERE deleted = 0 AND is_dir = 0
GROUP BY agent_id
ORDER BY total_bytes DESC;
```

*Indexed by `idx_files_agent_path` (`agent_id, path`, partial: `WHERE deleted = 0`) and `idx_files_agent` (`agent_id`) — see the [index catalog](#index-catalog).*

---

## blobs: deduplicated content

File bytes are stored once, keyed by their SHA-256 — when two agents write the same content, only one blob lands on disk, compressed by default.

```sql
CREATE TABLE IF NOT EXISTS blobs (
    content_hash    TEXT PRIMARY KEY,
    content         BLOB NOT NULL,
    compressed      INTEGER NOT NULL DEFAULT 0,
    ref_count       INTEGER NOT NULL DEFAULT 1
);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `content_hash` | TEXT | PRIMARY KEY | SHA-256 hex digest of the uncompressed bytes. |
| `content` | BLOB | NOT NULL | The bytes — zstd-compressed when the flag says so. |
| `compressed` | INTEGER | NOT NULL, default 0 | 1 = stored zstd-compressed, 0 = raw. |
| `ref_count` | INTEGER | NOT NULL, default 1 | How many file rows point here; drops when files are deleted, and at <= 0 the blob can be collected. |

### Behavior notes

- **Dedup.** A second write of identical content stores nothing new — `ref_count` goes up instead.
- **Compression.** On by default: bytes pass through zstandard level 3 before storage, and the `compressed` flag tells readers whether to decompress on the way out.
- **Garbage collection.** `BlobStore.gc()` removes every row with `ref_count <= 0`. That is safe because soft-deleted files keep their `content_hash`, so checkpoints can still restore them.

### Paste-ready queries

```sql
-- Blob store statistics
SELECT
    COUNT(*) as total_blobs,
    SUM(LENGTH(content)) as total_stored_bytes,
    SUM(ref_count) as total_references
FROM blobs;

-- Find orphaned blobs (eligible for GC)
SELECT content_hash, LENGTH(content) as stored_size, ref_count
FROM blobs
WHERE ref_count <= 0;

-- Largest blobs by stored size
SELECT content_hash, LENGTH(content) as stored_bytes, ref_count
FROM blobs
ORDER BY LENGTH(content) DESC
LIMIT 10;

-- Blobs shared across multiple files
SELECT content_hash, ref_count
FROM blobs
WHERE ref_count > 1
ORDER BY ref_count DESC;
```

---

## schema_version: the migration record

A one-row-per-migration ledger, so any copy of `bene.db` can prove which schema it carries.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

### Column guide

| Column | Type | Constraints | Description |
|---|---|---|---|
| `version` | INTEGER | PRIMARY KEY | The migration number. Current: 6. |
| `applied_at` | TEXT | NOT NULL, auto-generated | When that migration ran. |

### Migration mechanics

- First initialization inserts version 7.
- On later opens, a database that trails the code's `SCHEMA_VERSION` is brought forward by incremental migrations through `_apply_migrations()`.
- Future steps land as `if from_version < N:` blocks in `bene/schema.py`.

### Paste-ready queries

```sql
-- Check current schema version
SELECT MAX(version) as current_version FROM schema_version;

-- Migration history
SELECT version, applied_at FROM schema_version ORDER BY version;
```

---

<a id="relationships"></a>

## How the tables join up

Every relationship in the schema, in one view:

```text
agents.agent_id    ----<  files.agent_id           (one agent, many files)
agents.agent_id    ----<  tool_calls.agent_id      (one agent, many tool calls)
agents.agent_id    ----<  state.agent_id           (one agent, many state keys)
agents.agent_id    ----<  events.agent_id          (one agent, many events)
agents.agent_id    ----<  checkpoints.agent_id     (one agent, many checkpoints)
agents.agent_id    <---   agents.parent_id         (self-referencing parent/child)
blobs.content_hash <---   files.content_hash       (one blob, many file versions)
tool_calls.call_id <---   tool_calls.parent_call_id (self-referencing call chain)
events.event_id    <---   checkpoints.event_id     (checkpoint watermark into event stream)
```

These links are not decorative. Every connection sets `PRAGMA foreign_keys=ON`, so SQLite itself refuses orphaned rows — a file can never belong to an agent that does not exist.

---

<a id="index-reference"></a>

## Index catalog

Each index that ships with the schema, and the query shape it serves:

| Table | Index Name | Columns | Partial? | Purpose |
|---|---|---|---|---|
| agents | `idx_agents_status` | `status` | No | Filter agents by lifecycle state |
| agents | `idx_agents_parent` | `parent_id` | No | Find child agents |
| files | `idx_files_agent_path` | `agent_id, path` | Yes (`deleted=0`) | Fast file lookup excluding deleted |
| files | `idx_files_agent` | `agent_id` | No | List all files for an agent |
| tool_calls | `idx_tool_calls_agent` | `agent_id, started_at` | No | Chronological call history |
| tool_calls | `idx_tool_calls_tool` | `tool_name` | No | Filter by tool type |
| tool_calls | `idx_tool_calls_status` | `status` | No | Find calls by status |
| events | `idx_events_agent_time` | `agent_id, timestamp` | No | Chronological event stream |
| events | `idx_events_type` | `event_type` | No | Filter by event type |
| checkpoints | `idx_checkpoints_agent` | `agent_id, created_at` | No | Chronological checkpoint listing |
