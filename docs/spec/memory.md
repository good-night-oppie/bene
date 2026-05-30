# bene.memory

> Cross-agent episodic memory store: typed entries recording observations,
> results, signals, insights, and errors. Searchable via SQLite FTS5.
> Distinct from `bene.skills` (procedural patterns) — memory records
> **what was observed**; skills record **how to do something**.

**Reference impl**: `ionq/memory.py` `class MemoryStore`, `class MemoryEntry`

## Design intent

Project-wide memory shared by all agents in the same database. Each entry has a typed tag (`observation | result | skill | insight | error`), free-text content, optional human-readable `key`, and JSON metadata. Search is FTS5 with porter stemming over content and key.

The distinction from `bene.skills`:

| | bene.memory | bene.skills |
|---|---|---|
| Records | What was observed | How to do something |
| Shape | Free text + metadata | Parameterized template |
| Use | Recall during reasoning | Apply during proposal |
| Outcome tracking | No | Yes (use/success counts) |

## Public surface

### `class MemoryEntry`

```python
@dataclass
class MemoryEntry:
    memory_id: int
    agent_id: str
    type: str  # one of MEMORY_TYPES
    key: str | None
    content: str
    metadata: dict[str, Any]
    created_at: str
```

**Intent**: typed record. `type` controls how downstream consumers route the entry. `key` is optional but useful for collision-resistant lookups (e.g. a unique experiment ID).

**Methods**:
```python
MemoryEntry.to_dict() -> dict[str, Any]
```

### Type vocabulary

```python
MEMORY_TYPES = ("observation", "result", "skill", "insight", "error")
```

**Intent**: closed vocabulary. Writes with any other type raise.

- `observation` — neutral signal from the environment
- `result` — final output of an action
- `skill` — a procedural finding (typically also saved to `bene.skills`)
- `insight` — distilled reasoning, often supervisor-injected
- `error` — failure record for later avoidance

### `class MemoryStore`

```python
MemoryStore(conn: sqlite3.Connection) -> MemoryStore
```

#### Write

```python
write(agent_id: str, content: str, *, type: str = "observation",
      key: str | None = None,
      metadata: dict[str, Any] | None = None) -> int
```

**Intent**: append a memory entry. Returns `memory_id`. `type` must be in `MEMORY_TYPES`.

#### Search + read

```python
search(query: str, *, limit: int = 10, type: str | None = None,
       agent_id: str | None = None) -> list[MemoryEntry]
```

**Intent**: full-text search with optional type / agent filters. Ranked by BM25.

```python
get(memory_id: int) -> MemoryEntry | None
list(*, type: str | None = None, agent_id: str | None = None,
     limit: int = 50, offset: int = 0) -> list[MemoryEntry]
```

#### Maintenance

```python
delete(memory_id: int) -> bool
stats() -> dict[str, Any]
```

## Behavioral example

```python
mem = MemoryStore(engine.conn)

# Agent records a finding
mid = mem.write(
    agent_id="agent-01",
    content="Accuracy improved to 87% by switching to ensemble voting.",
    type="result",
    key="ensemble-voting-v3",
    metadata={"benchmark": "text_classify", "iteration": 5},
)

# Later, a different agent searches
hits = mem.search("ensemble accuracy", type="result", limit=5)
for h in hits:
    # h.content -> "Accuracy improved to 87%..."
    # h.metadata -> {"benchmark": "text_classify", "iteration": 5}
    ...
```

## Implementer notes

- **FTS5 invariant**: triggers keep the FTS virtual table in sync with `memory` on insert/update/delete. Same pattern as `bene.skills`.
- **Type vocabulary is closed**. Do not add new types ad-hoc without coordinating downstream consumers (`bene.proposer` reads type-tagged history). If you need a new category, add it explicitly to `MEMORY_TYPES` and update the contract page.
- **No outcome tracking** at the memory level (unlike skills). If a memory entry leads to a skill, the skill carries the outcome data — memory stays append-only and audit-trail-clean.
- **`key` uniqueness is not enforced** but is convenient for caller-side dedup. Bene may add an optional uniqueness constraint as a future feature; the contract is "writes never fail on key collision in this version".
- **Cross-agent sharing**: every agent in the project sees every memory entry. There is no per-agent silo. Filter by `agent_id` at read time if you want scoped views.

## Cross-references

- **Depends on**: `bene.core` (shared SQLite connection)
- **Used by**: `bene.search` (proposer context enrichment via prior results/errors)
- **Sibling**: `bene.skills` (procedural counterpart)
