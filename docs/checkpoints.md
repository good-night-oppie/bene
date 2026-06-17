# Checkpoints — undo for agents

Checkpoint an agent before risky work, and a failed run costs one restore command instead of a rebuild. bene captures full agent state on demand; rewind to any capture, or diff two.

> **One call to save, one to rewind, one to diff — all history in one SQLite file on your machine.**


---

## Save a known-good state

```python
cp = db.checkpoint(agent_id, label="before-migration")
```

```bash
bene checkpoint <agent-id> --label "before-migration"
```

Each snapshot records:

- every VFS file, as content-addressable blob references — no duplicate bytes
- every key written through `db.set_state(...)`
- its timestamp, plus any metadata you attach

Snapshots write blob pointers, not file copies, so take them freely.

### Automatic snapshots

`ClaudeCodeRunner` checkpoints itself every `checkpoint_interval` iterations (10 by default):

```yaml
# bene.yaml
ccr:
  checkpoint_interval: 10
```

---

## Rewind a bad run

Roll back to any capture:

```python
db.restore(agent_id, checkpoint_id)
```

```bash
bene restore <agent-id> --checkpoint <checkpoint-id>
```

Restore is pure SQL — bene rewrites the agent's file rows and state rows — so it lands in milliseconds however much changed, touches no other agent, and never leaves your machine.

The habit worth building: snapshot, attempt, roll back on failure.

```python
cp = db.checkpoint(agent_id, label="pre-migration")
try:
    result = await ccr.run_agent(agent_id, "Migrate schema to v3")
except Exception:
    db.restore(agent_id, cp)
    raise
```

---

## See what changed

Diff any two captures:

```python
diff = db.diff_checkpoints(agent_id, checkpoint_id_a, checkpoint_id_b)
```

```bash
bene diff <agent-id> --from <checkpoint-id-A> --to <checkpoint-id-B>
```

Each diff reports:

- **Files added** — paths that exist only in snapshot B
- **Files removed** — there in A, gone in B
- **Files modified** — the same path with a different SHA-256 on each side
- **State changed** — KV keys gained, dropped, or given new values
- **Tool calls between** — calls made between the two captures

A typical report — a table keyed by path and status (no file sizes), then the state and tool-call sections:

```text
           File Changes
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Status     ┃ Path               ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ ADDED      │ /tests/test_auth.py│
│ MODIFIED   │ /src/auth.py       │
│ REMOVED    │ /src/auth_legacy.py│
└────────────┴────────────────────┘

          State Changes
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Status     ┃ Key      ┃ Value                        ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ MODIFIED   │ progress │ 75 -> 100                    │
│ MODIFIED   │ status   │ "in-progress" -> "complete"  │
└────────────┴──────────┴──────────────────────────────┘

      Tool Calls Between Checkpoints
┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ Tool      ┃ Status  ┃ Duration ┃ Tokens ┃
┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ read_file │ success │ 15ms     │ 120    │
└───────────┴─────────┴──────────┴────────┘
```

When a section is empty, the console outputs `No state changes` or `No tool calls between checkpoints`.

With `--json`, the same diff comes back as `{"files": {"added": [...], "removed": [...], "modified": [...]}, "state": {"added": {...}, "removed": {...}, "modified": {...}}, "tool_calls": [...]}`.

### Compare two attempts

Snapshot each approach, then diff them:

```python
cp_a = db.checkpoint(agent_id, label="approach-A")
# ... run approach A ...
cp_b = db.checkpoint(agent_id, label="approach-B")

# Compare
diff = db.diff_checkpoints(agent_id, cp_a, cp_b)
```

---

## Find a capture

List an agent's captures:

```python
cps = db.list_checkpoints(agent_id)
# [{"checkpoint_id": "01K...", "label": "before-migration", "created_at": "..."}]
```

```bash
bene checkpoints <agent-id>
bene --json checkpoints <agent-id>
```

### Annotate a snapshot

Labels name a capture; metadata explains it — test results, triggers, notes:

```python
cp = db.checkpoint(agent_id, label="v2-attempt")

# The Bene facade takes just a label. For rich metadata, call the manager directly:
# db.checkpoints.create(agent_id, label="v2-attempt", metadata={
#     "notes": "Switched to JWT — session-based auth removed",
#     "test_results": {"passed": 14, "failed": 0},
#     "triggered_by": "CI pipeline run #428",
# })
```

It shows up in `bene checkpoints <agent-id>` and the dashboard's Checkpoints tab.

---

## What snapshots cost

Almost nothing. File bodies live once in the blob store (SHA-256 keys, zstd compression); a checkpoint is just pointers. Two captures sharing 95% of their files cost barely more than one.

Reclaim blobs nothing references anymore:

```python
db.blobs.gc()  # removes blobs whose ref_count has dropped to 0
```

---

## Move it to another machine

Exporting an agent carries all its checkpoints in one portable file:

```bash
# Export the entire agent (includes all checkpoints)
bene export <agent-id> -o agent-snapshot.db

# On another machine
bene import agent-snapshot.db
```
