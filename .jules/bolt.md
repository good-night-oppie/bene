## 2024-05-19 - N+1 query bottlenecks in SQLite Dashboards

**Learning:** In SQLite, using `LEFT JOIN (SELECT agent_id, COUNT(*) ... GROUP BY agent_id)` across multiple large tables forces full table scans and temporary table materialization. For dashboards showing listing API routes, this causes a severe N+1-like bottleneck, taking >1s even with `LIMIT 50`.
**Action:** Replace these with correlated scalar subqueries `(SELECT COUNT(*) FROM table WHERE agent_id = a.agent_id)`. Also, apply limits in a CTE *before* the correlated subquery, e.g. `WITH top_agents AS (SELECT ... LIMIT 50) SELECT ..., (SELECT COUNT(*) ...) FROM top_agents`. This allows SQLite to use existing `agent_id` indexes efficiently, achieving up to a 5000x speedup for single-row lookups and 500x for paginated queries.

## 2025-02-18 - Avoid SQLite Temp B-Trees on Append-Only Event Tables

**Learning:** In the `events` table (an append-only audit trail), the primary access pattern is fetching an agent's most recent events using `ORDER BY event_id DESC` or `MAX(event_id)`. Despite having an index on `(agent_id, timestamp)`, SQLite was forced to use a temporary B-tree for sorting and grouping by `event_id`, which severely impacts performance as the journal grows large.
**Action:** Always create compound indexes that cover both the filtering condition (`agent_id`) and the sorting/aggregation condition (`event_id`) directly, e.g., `(agent_id, event_id)`. This guarantees O(1) reads for `MAX()` and prevents the use of temp B-trees for `ORDER BY`, yielding ~100x to ~350x speedups in high-volume tables.

## 2025-02-23 - Index modifications require renaming for deployment to existing DBs

**Learning:** When modifying an existing `CREATE INDEX IF NOT EXISTS` statement inline (e.g. adding columns to a compound index in dynamically initialized tables like `skill_uses` or `skill_lifecycle`), keeping the original index name causes SQLite to silently skip the creation on existing databases because an index with that name already exists.
**Action:** Always append a version suffix (e.g., `_v2`) to the index name when changing an index definition without a formal `DROP INDEX` or migration script. This guarantees the improved index gets deployed to existing users.

## 2024-07-12 - Avoid SQLite Temp B-Trees on ORDER BY Queries

**Learning:** When querying SQLite with an `ORDER BY col1 DESC, col2 DESC` clause (like in `memory` cross-agent queries fetching recent records), if an index only covers `col1` or covers both but in default `ASC` order, SQLite falls back to a Temp B-Tree. This makes fetch times $O(N \log N)$ instead of $O(1)$, which is a huge bottleneck as the table grows.
**Action:** Define compound indexes that exactly match the `ORDER BY` conditions, including the `DESC` keyword explicitly, such as `CREATE INDEX idx_name ON table(col1 DESC, col2 DESC)`.
## 2024-07-29 - [Eliminating SQLite Temp B-Tree on Dashboard Sorting]
**Learning:** SQLite defaults to O(N log N) Temp B-Tree sorts when queried via `ORDER BY created_at DESC` on unindexed columns, which severely impacts dashboard and UI server load times as the agent table grows.
**Action:** Always add an index (e.g. `idx_agents_created_at_v2 ON agents(created_at DESC)`) for frequently ordered columns in SQLite, and remember to incrementally update `SCHEMA_VERSION`, `MIGRATION_VX_SQL` and `docs/schema.md` to prevent accuracy gate checks from failing.
