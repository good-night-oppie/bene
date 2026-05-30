# bene.skills

> The moat. Cross-agent, cross-run procedural memory store: every agent in
> the project can save reusable solution patterns ("skills") and any other
> agent can later search, apply, and grade them. Skills are templates with
> typed parameters and outcome tracking, distinct from `bene.memory` which
> records observations.

**Reference impl**: `ionq/skills.py` `class SkillStore`, `class Skill`

## Design intent

A skill is a *parameterized prompt template* with a name, description, tag set, and lifetime usage statistics. The store is project-wide: any agent in the same database can search, read, apply, or grade any other agent's skill. This sharing is the point — reliability information compounds without a central curator. Search uses SQLite FTS5 with porter stemming over name, description, tags, and template body, ranked by BM25.

## Public surface

### `class Skill`

```python
@dataclass
class Skill:
    skill_id: int
    name: str
    description: str
    template: str
    tags: list[str]
    source_agent_id: str | None
    use_count: int
    success_count: int
    created_at: str
    updated_at: str
```

**Methods**:

```python
Skill.params() -> list[str]
```

**Intent**: introspect the template's placeholder names (e.g. for `"hello {name}"` returns `["name"]`). Used by callers building forms or validating before apply.

```python
Skill.apply(**kwargs: str) -> str
```

**Intent**: substitute placeholders with provided values. Unrecognized keys silently ignored; missing keys raise.

```python
Skill.to_dict() -> dict[str, Any]
```

**Intent**: serialize to a dict suitable for JSON, including derived `success_rate`.

### `class SkillStore`

```python
SkillStore(conn: sqlite3.Connection) -> SkillStore
```

**Intent**: open a store backed by a shared SQLite connection (typically `Engine.conn`).

#### Save

```python
save(*, name: str, description: str, template: str,
     source_agent_id: str | None = None,
     tags: list[str] | None = None) -> int
```

**Intent**: persist a new skill. Returns the new `skill_id`. Names need not be unique.

#### Search + list

```python
search(query: str, limit: int = 10, tag: str | None = None) -> list[Skill]
```

**Intent**: full-text search using FTS5 BM25 ranking over name, description, tags, and template. `tag` (if supplied) is an exact-match filter applied after FTS ranking. Supports phrases, NOT, wildcards via FTS5 syntax.

```python
get(skill_id: int) -> Skill | None
list(*, tag: str | None = None, source_agent_id: str | None = None,
     order_by: str = "created_at", limit: int = 50, offset: int = 0) -> list[Skill]
```

**Intent**: typed lookups. `order_by` accepts `created_at | success_count | use_count | name`. Other values fall back to `created_at`.

#### Outcome tracking

```python
record_outcome(skill_id: int, success: bool) -> None
```

**Intent**: increment `use_count`; increment `success_count` only on `success=True`. Updates `updated_at`. Used by agents to grade applied skills so future searches can rank by reliability.

#### Maintenance

```python
delete(skill_id: int) -> bool
stats() -> dict[str, Any]
import_from_paths(paths) -> int
```

**Intent**: `delete` returns whether a row was removed. `stats` returns total count + top skills by `success_rate`. `import_from_paths` scans the given paths for `*/SKILL.md` files and bulk-inserts (idempotent on `name`).

## Behavioral example

```python
store = SkillStore(engine.conn)

sid = store.save(
    source_agent_id="agent-01",
    name="ensemble_classifier",
    description="Improve classification accuracy with ensemble voting",
    template="Use {n_models}-model ensemble with {voting} voting; threshold={threshold}.",
    tags=["classification", "ensemble", "accuracy"],
)

# Another agent later
hits = store.search("classification accuracy")
for s in hits:
    rendered = s.apply(n_models="3", voting="majority", threshold="0.5")
    # ... feed rendered into proposer prompt ...
    store.record_outcome(s.skill_id, success=True)
```

## Implementer notes

- **FTS5 + porter stemming** is the search backbone. Triggers must keep the FTS virtual table synchronized with the main `agent_skills` table on insert/update/delete. The reference impl bundles these triggers into the schema migration; bene must do the same.
- **Names not unique by design**: two agents may discover the same skill name independently. Disambiguate by `skill_id`, not by name. `import_from_paths` is the only path that dedupes by name (skipping existing).
- **Project-wide sharing is the moat.** Do not introduce per-agent skill silos as an "optimization" — the value of the store is that one agent's discovery benefits all subsequent agents.
- **Success rate is derived, not stored.** `to_dict()` computes `success_count / use_count` on the fly when `use_count > 0`; never store the ratio directly (race-prone).
- **Tag exact-match after FTS rank**: search filters by FTS first, then post-filters by tag. Implementer must preserve this order so BM25 relevance dominates.

## Cross-references

- **Depends on**: `bene.core` (for the shared SQLite connection + agent lifecycle)
- **Used by**: `bene.proposer` (prompt construction), `bene.search` (cross-run seeding via knowledge-store singleton agent)
