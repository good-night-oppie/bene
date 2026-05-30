# bene.core

> SQLite-backed engine providing isolated per-agent virtual filesystems, durable
> state, tool-call tracking, checkpoint/restore, and a full audit-trail event
> journal. All other bene modules consume `bene.core` as substrate.

**Reference impl**: `ionq/core.py` `class ionq`

## Design intent

One instance per `.db` file. Thread-safe. Every observable behavior is recorded in an append-only event journal — agents can be inspected, paused, resumed, checkpointed, and reconstructed from history alone. File contents are content-addressed via a separate blob store so identical writes deduplicate automatically.

## Public surface

### `class Engine`

Implementer note: the reference impl class is named `ionq`; in bene this is renamed to `Engine` to avoid type-name shadowing. The capability surface is identical.

```python
Engine(db_path: str = "bene.db", compression: str = "zstd") -> Engine
```

**Intent**: open or create a bene database. Schema is initialized lazily on first open.

**Post-conditions**:
- Database file exists at `db_path`
- WAL journaling enabled
- Foreign keys enforced
- All public methods become callable

#### Agent lifecycle

```python
spawn(name: str, *, config: dict | None = None, parent_id: str | None = None,
      metadata: dict | None = None, agent_id: str | None = None) -> str
```

**Intent**: create a new agent with an isolated VFS rooted at `/`. Returns the agent's ULID.

**Pre-conditions**:
- If `agent_id` is supplied, caller is responsible for its uniqueness (typically pre-allocated for retry-idempotent Activity execution).
- If `parent_id` is supplied, that agent must exist.

**Post-conditions**:
- Agent row exists with `status='created'`
- Root directory `/` exists in the agent's VFS
- An `agent_spawn` event is recorded

```python
status(agent_id: str) -> dict
list_agents(status_filter: str | None = None) -> list[dict]
set_status(agent_id: str, status: str, pid: int | None = None) -> None
pause(agent_id: str) -> None
resume(agent_id: str) -> None
kill(agent_id: str) -> None
complete(agent_id: str) -> None
fail(agent_id: str, error: str | None = None) -> None
heartbeat(agent_id: str) -> None
get_singleton(name: str, aliases: Sequence[str] = ()) -> str | None
get_or_create_singleton(name: str, *, config: dict | None = None,
                        aliases: Sequence[str] = ()) -> str
```

**Intent**: agents traverse a small state machine (`created → running ↔ paused → completed | failed | killed`). `get_or_create_singleton` is used for cross-session persistent agents (skill knowledge store, shared coordination).

#### Virtual filesystem

```python
write(agent_id: str, path: str, content: bytes) -> None
read(agent_id: str, path: str) -> bytes
delete(agent_id: str, path: str) -> None
exists(agent_id: str, path: str) -> bool
ls(agent_id: str, path: str = "/") -> list[dict]
stat(agent_id: str, path: str) -> dict
mkdir(agent_id: str, path: str) -> None
file_history(agent_id: str, path: str) -> list[dict]
```

**Intent**: each agent owns its own filesystem. Writes never overwrite — they append a new version. Reads return the latest non-deleted version. Deletes are soft (mark deleted, keep blob) so checkpoint restore can recover.

**Cross-agent isolation guarantee**: `Engine.read(a, "/x")` cannot observe writes made via `Engine.write(b, "/x")` for any `a != b`. Strict.

**Behavioral example**:
```python
db = Engine(":memory:")
a = db.spawn("alpha")
b = db.spawn("beta")
db.write(a, "/notes.md", b"alpha-notes")
db.write(b, "/notes.md", b"beta-notes")
assert db.read(a, "/notes.md") == b"alpha-notes"
assert db.read(b, "/notes.md") == b"beta-notes"
```

#### Durable state

```python
get_state(agent_id: str, key: str) -> Any
get_state_or(agent_id: str, key: str, default: Any = None) -> Any
set_state(agent_id: str, key: str, value: Any) -> None
delete_state(agent_id: str, key: str) -> None
get_all_state(agent_id: str) -> dict
```

**Intent**: per-agent key/value store separate from VFS. Values are JSON-serializable. Survives restart, restored by checkpoints.

#### Tool-call tracking

```python
log_tool_call(agent_id: str, tool_name: str, input_data: dict,
              parent_call_id: str | None = None) -> str
start_tool_call(call_id: str) -> None
complete_tool_call(call_id: str, output: dict, *, status: str = "success",
                   token_count: int | None = None, error_message: str | None = None) -> None
get_tool_calls(agent_id: str, *, tool_name: str | None = None,
               status: str | None = None, limit: int = 100) -> list[dict]
```

**Intent**: every tool invocation is recorded with input, output, status, duration, optional token count. Enables post-hoc auditing of agent behavior.

#### Checkpoints

```python
checkpoint(agent_id: str, label: str | None = None) -> str
restore(agent_id: str, checkpoint_id: str) -> None
list_checkpoints(agent_id: str) -> list[dict]
diff_checkpoints(agent_id: str, from_cp: str, to_cp: str) -> dict
```

**Intent**: snapshot the agent's files + state at a point in time, restore back to it later. Round-trip is lossless for VFS + state.

#### Querying

```python
query(sql: str, params: tuple = ()) -> list[dict]
```

**Intent**: read-only SQL escape hatch for ad-hoc queries (dashboards, debugging). Write statements raise.

#### Index + search

```python
build_index(agent_id: str) -> str
search(query: str, agent_id: str | None = None, limit: int = 50) -> list[dict]
```

**Intent**: utility helpers — `build_index` writes a `/index.md` summarizing an agent's tree; `search` performs full-text grep across file contents (optionally agent-scoped).

#### Lifecycle

```python
close() -> None
__enter__() -> Engine
__exit__(*args) -> None
```

**Intent**: usable as a context manager. `close` releases the thread-local DB connection.

## Implementer notes

- **Connections are thread-local**. Dependent components (blobs, events, checkpoints) must use the same thread's connection — otherwise WAL contention deadlocks. The reference impl exposes a `_get_conn` callable that dependent components call lazily; bene must preserve this contract.
- **Writes are versioned, deletes are soft**. Old blobs are retained so checkpoint restore + file history work. Garbage collection of unreachable blobs is a separate concern, not part of this surface.
- **`agent_id` parameters that allow pre-allocation** (e.g. `spawn`) exist so callers running on top of retry-driven orchestrators (Temporal Activities) can supply a deterministic ID for idempotency.
- **Concurrent spawn** must retry on `database is locked` for at least a few attempts. The reference impl uses 3 attempts with backoff; bene may choose a different value but the contract is "transient lock errors must not surface to the caller on first attempt".
- **Singleton agents** are looked up by name OR aliases in order of preference. Used for cross-session knowledge stores that should outlive any single session.
- **Path normalization**: all paths are converted to canonical POSIX (`/foo/bar`, no trailing slash except root). Implementer notes for bene: do not depend on the reference impl's specific normalization helper; re-derive from POSIX path semantics.

## Cross-references

- **Depends on**: nothing (foundation module)
- **Used by**: `bene.skills`, `bene.memory`, `bene.shared_log`, `bene.runner`, `bene.evaluator`, `bene.search`
