## 2024-05-19 - N+1 query bottlenecks in SQLite Dashboards

**Learning:** In SQLite, using `LEFT JOIN (SELECT agent_id, COUNT(*) ... GROUP BY agent_id)` across multiple large tables forces full table scans and temporary table materialization. For dashboards showing listing API routes, this causes a severe N+1-like bottleneck, taking >1s even with `LIMIT 50`.
**Action:** Replace these with correlated scalar subqueries `(SELECT COUNT(*) FROM table WHERE agent_id = a.agent_id)`. Also, apply limits in a CTE *before* the correlated subquery, e.g. `WITH top_agents AS (SELECT ... LIMIT 50) SELECT ..., (SELECT COUNT(*) ...) FROM top_agents`. This allows SQLite to use existing `agent_id` indexes efficiently, achieving up to a 5000x speedup for single-row lookups and 500x for paginated queries.
