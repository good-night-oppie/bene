## 2024-05-19 - N+1 query bottlenecks in SQLite Dashboards

**Learning:** In SQLite, using `LEFT JOIN (SELECT agent_id, COUNT(*) ... GROUP BY agent_id)` across multiple large tables forces full table scans and temporary table materialization. For dashboards showing listing API routes, this causes a severe N+1-like bottleneck, taking >1s even with `LIMIT 50`.
**Action:** Replace these with correlated scalar subqueries `(SELECT COUNT(*) FROM table WHERE agent_id = a.agent_id)`. Also, apply limits in a CTE *before* the correlated subquery, e.g. `WITH top_agents AS (SELECT ... LIMIT 50) SELECT ..., (SELECT COUNT(*) ...) FROM top_agents`. This allows SQLite to use existing `agent_id` indexes efficiently, achieving up to a 5000x speedup for single-row lookups and 500x for paginated queries.

## 2025-02-18 - Avoid SQLite Temp B-Trees on Append-Only Event Tables

**Learning:** In the `events` table (an append-only audit trail), the primary access pattern is fetching an agent's most recent events using `ORDER BY event_id DESC` or `MAX(event_id)`. Despite having an index on `(agent_id, timestamp)`, SQLite was forced to use a temporary B-tree for sorting and grouping by `event_id`, which severely impacts performance as the journal grows large.
**Action:** Always create compound indexes that cover both the filtering condition (`agent_id`) and the sorting/aggregation condition (`event_id`) directly, e.g., `(agent_id, event_id)`. This guarantees O(1) reads for `MAX()` and prevents the use of temp B-trees for `ORDER BY`, yielding ~100x to ~350x speedups in high-volume tables.

## 2025-02-23 - Index modifications require renaming for deployment to existing DBs

**Learning:** When modifying an existing `CREATE INDEX IF NOT EXISTS` statement inline (e.g. adding columns to a compound index in dynamically initialized tables like `skill_uses` or `skill_lifecycle`), keeping the original index name causes SQLite to silently skip the creation on existing databases because an index with that name already exists.
**Action:** Always append a version suffix (e.g., `_v2`) to the index name when changing an index definition without a formal `DROP INDEX` or migration script. This guarantees the improved index gets deployed to existing users.

## 2025-02-23 - Index on event filtering in SQLite

**Learning:** When fetching events filtered by `event_type` and sorted by `event_id DESC`, SQLite has to scan the whole index `idx_events_agent_event_id` backwards to find enough matches for the limit. This creates a severe N+1-like bottleneck or a slow scan for large `events` tables (e.g. agent audit trails).
**Action:** Always create a compound index `idx_events_agent_type_event_id` on `(agent_id, event_type, event_id)` to ensure O(1) matching with limit bounds and avoid scanning agent history, significantly improving query speed on large tables.
