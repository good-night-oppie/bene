# Architecture diagrams

Three pictures of how BENE fits together: the single-file **Nexus**, the
**engram compression ladder**, and the **autonomy ladder**. Each diagram is the
shape; the prose says what it's load-bearing for.

## The Nexus — many isolated agents, one file

Every agent has its own VFS, event journal, checkpoints, and traces — but they
all live in **one** SQLite database. That single file is the Nexus: the join
point for the whole swarm, and the thing you copy, diff, or check into git.
(WAL mode keeps recent commits in a `bene.db-wal` sidecar until checkpoint/close,
so copy the db when the process is idle — or copy the `-wal`/`-shm` files too.)

```mermaid
flowchart TB
    subgraph agents["Isolated agents (SQL-scoped by agent_id)"]
        A1["researcher<br/>VFS · events · checkpoints"]
        A2["refactor-bot<br/>VFS · events · checkpoints"]
        A3["reviewer<br/>VFS · events · checkpoints"]
    end
    A1 --> DB
    A2 --> DB
    A3 --> DB
    DB[("bene.db — one auditable<br/>SQLite file · the Nexus")]
    DB --> S["shared log · blobs · engrams"]
```

*Load-bearing:* an agent's own `fs_*` tools are scoped to its `agent_id`, so in
normal operation "many agents, one file" doesn't mean agents stumble into each
other. It is logical namespacing, not a hard authorization boundary — the
operator surface (`Bene.read`/`query`, the `agent_read`/`agent_write` MCP tools)
takes an explicit `agent_id` and can cross agents by design. The union is the
audit surface.

## The engram compression ladder

Execution traces are stored on a tiered ladder (0–4): raw at the bottom,
progressively compressed summaries above. Retrieval searches the cheap high
tiers first and drills into detail only on a hit — so memory stays searchable as
the corpus grows.

```mermaid
flowchart LR
    T0["Tier 0<br/>raw traces<br/>(every turn)"] --> T1["Tier 1<br/>granule summaries"]
    T1 --> T2["Tier 2"]
    T2 --> T3["Tier 3"]
    T3 --> T4["Tier 4<br/>most compressed"]
    Q(["bene retrieve"]) -. "search cheap tiers,<br/>drill down on a hit" .-> T3
    Q -.-> T2
```

*Load-bearing:* capture is the default (every run drops a tier-0 trace), and the
ladder is what keeps "remember everything" from becoming "scan everything."

## The autonomy ladder (L0 → L4)

Agents operate at a rung. Computed trust (four signals + a composite) raises the
floor an agent is allowed to reach — but the top rung, autonomous promotion, is
**capped below L4 by the engine** and only a human grant crosses it.

```mermaid
flowchart TB
    L0["L0 · Observe"] --> L1["L1 · Suggest"]
    L1 --> L2["L2 · Act in sandbox"]
    L2 --> L3["L3 · Act on shared state"]
    L3 --> L4["L4 · Autonomous-promote"]
    Trust["computed trust<br/>(4 signals + composite)"] -. "informs grant decisions<br/>(does not auto-raise the level)" .-> L3
    Human["human grant<br/>(--by human:name)"] ==> L4
```

*Load-bearing:* autonomy is *earned* from observed behavior, not asserted.
Shared-state actions live at **L3**; the top rung — **L4**, autonomous
self-promotion — is the one that always requires a human grant.

---

*Diagrams are Mermaid; the docs site renders them inline. Grounded in
`bene/kernel/harness/autonomy.py` (the L0–L4 labels), the engram tier model, and
the single-file Nexus design. Source: edit this markdown, never the generated
HTML.*
