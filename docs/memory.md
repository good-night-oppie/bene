# Cross-Agent Memory

Write a finding down once and any agent that runs later — next iteration, next session, another worker — can search for it.

> **One agent's lesson becomes every agent's context: a single shared, full-text-searchable memory for the whole project.**


Clean-room build of an idea from [claude-mem](https://github.com/thedotmack/claude-mem) (AGPL-3.0) — see [Credits](#credits).

---

## Start Here

Hand `MemoryStore` your connection; every agent sharing the `.db` file shares the store.

```python
from bene import Bene
from bene.memory import MemoryStore

bene = Bene("project.db")
mem  = MemoryStore(bene.conn)

# Spawn the agent first — memory rows FK to agents; spawn returns the id string
agent_id = bene.spawn("proposer-iter-3")

# Any agent writes a result
mid = mem.write(
    agent_id=agent_id,
    content="Ensemble voting with 3 Sonnet calls achieved accuracy=0.847.",
    type="result",
    key="iter3-best",
    metadata={"accuracy": 0.847, "cost": 18.2},
)

# Any other agent can search across all memory
hits = mem.search("ensemble accuracy")
for h in hits:
    print(h.content)
```

Full demo: [examples/memory_search.py](../examples/memory_search.py).

---

## Choose a Type Before You Write

Each entry carries a type; failure hunters filter to `error`.

| Type | Use case |
|------|----------|
| `observation` | Runtime findings, intermediate results |
| `result` | Final outputs, benchmark scores |
| `skill` | Reusable patterns, code templates |
| `insight` | Analysis, lessons learned |
| `error` | Known failure modes to avoid |

---

## Search What Earlier Agents Learned

### `MemoryStore.search(query, limit, type, agent_id) -> list[MemoryEntry]`

Queries hit SQLite FTS5 with porter stemming, ranked by BM25 relevance.

FTS5 query syntax works as-is:

- Phrase: `"chain of thought"`
- NOT: `reasoning NOT error`
- OR: `ensemble OR majority`
- Wildcard: `accurac*`

```python
# Search across all agents, all types
hits = mem.search("ensemble voting math", limit=5)

# Filter to only 'error' entries
errors = mem.search("JSON decode", type="error")

# Filter to one agent
hits = mem.search("ensemble", agent_id=agent_id)
```

---

## Record, Browse, and Prune

### `MemoryStore.write(agent_id, content, type, key, metadata) -> int`

Stores one entry and returns its `memory_id`.

```python
mid = mem.write(
    agent_id="agent-01",
    content="Chain-of-thought prompting reduces errors by 23%.",
    type="skill",
    key="cot-numbered-steps",
    metadata={"benchmark": "math_rag"},
)
```

### `MemoryStore.list(agent_id, type, limit, offset) -> list[MemoryEntry]`

Newest first; narrow by agent or type, page with `offset`.

```python
# All entries
entries = mem.list()

# Skills only
skills = mem.list(type="skill", limit=20)

# Paginate
page2 = mem.list(offset=20, limit=20)
```

### `MemoryStore.get(memory_id) -> MemoryEntry | None`

Looks up one entry by primary key.

### `MemoryStore.get_by_key(key, agent_id) -> MemoryEntry | None`

Returns the newest entry carrying the given key.

### `MemoryStore.delete(memory_id) -> bool`

Removes an entry; a trigger also clears its FTS row.

### `MemoryStore.stats() -> dict`

Reports total count plus a per-type breakdown.

---

## Let the Meta-Harness Remember for You

After each iteration the meta-harness records improved harnesses and known failures; the proposer's prompt gains a "Cross-Session Memory" block built from prior searches.

**Restart a search and the proposer already knows what worked before.**

```python
# Memory is auto-written in _store_result() for improved/failed harnesses
# Memory is auto-queried in proposer._load_memory_context()
```

---

## Drive It from the Shell

Write, search, and list have shell verbs; `--json` makes the output pipeable.

```bash
# Write a memory entry
uv run bene memory write <agent_id> "Ensemble voting improved accuracy by 12%." --type insight --key ensemble-v1

# Full-text search
uv run bene memory search "ensemble accuracy"
uv run bene memory search "JSON error" --type error

# List recent entries
uv run bene memory ls
uv run bene memory ls --type result --limit 5

# JSON output for piping
uv run bene --json memory search "ensemble" | jq '.[].content'
```

---

## Call It from Claude Code

Agents reaching BENE over MCP get these memory tools:

```text
agent_memory_write   — persist a memory entry
agent_memory_search  — FTS5 search across all agents
agent_memory_read    — fetch by memory_id or list recent
```

---

## Check Where Your Data Lives

Nothing leaves your machine: memory is one SQLite table inside the same `.db` file as your agents — copy that file and you have copied the memory. An FTS5 virtual table powers search, kept in sync by triggers.

```sql
CREATE TABLE memory (
    memory_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    type        TEXT NOT NULL DEFAULT 'observation'
                CHECK (type IN ('observation','result','skill','insight','error')),
    key         TEXT,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
    content, key,
    type UNINDEXED, agent_id UNINDEXED, memory_id UNINDEXED, created_at UNINDEXED,
    tokenize = 'porter unicode61'
);
-- FTS is kept in sync via INSERT/UPDATE/DELETE triggers
```

---

## Credits

The seed idea — agents leaving compact, searchable notes for later sessions to retrieve — comes from Alex Newman's [claude-mem](https://github.com/thedotmack/claude-mem) ([@thedotmack](https://github.com/thedotmack)), AGPL-3.0. BENE diverges:

- storage is SQLite FTS5 rather than a separate file store
- many agents write and many agents read, instead of one agent
- entries carry a type (result, skill, error, insight, observation) so retrieval stays structured
- the meta-harness reads and writes memory automatically
