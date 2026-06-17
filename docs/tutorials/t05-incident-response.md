# Find What Changed in 12 Seconds

Diagnose a 2am production outage without leaving SQLite: two SELECT statements against `bene.db` take you from a 23% HTTP 500 rate to the single config line that caused it, and a third query produces the post-mortem numbers.

> **Because every agent write lands in an append-only journal, "what changed?" is a query — not a 90-minute investigation.**


*The recorded run: pager at 02:17, first query at 02:17:12, cause in hand at 02:17:24, then a hotfix that takes the error rate from 23% back to 0%.*

## The 2am question

It's 2am and 23% of HTTP requests are coming back as 500s. Whatever you do next, you are really asking one thing: what changed?

Without a journal, that answer is assembled by hand — grep the application logs, cross-check deploy history scattered across several systems, read recent commits, message whoever shipped last. Plan on 45 to 90 minutes. With BENE, every write any agent has ever made is already a timestamped row in one file, and the whole diagnosis below is two queries, including the `SELECT ... WHERE timestamp > ...` shape.

## Start from the symptoms

Ask the journal which errors are firing, from which agent, since when:

```sql
SELECT timestamp, agent_id, tool_name, error
FROM tool_calls
WHERE status = 'error'
  AND timestamp > datetime('now', '-1 hour')
ORDER BY timestamp DESC
LIMIT 20
```

```text
elapsed               agent_id      tool_name      error
T+48m05s              api-gateway   db_query       ConnectionPoolError: pool exhausted
T+48m04s              api-gateway   db_query       ConnectionPoolError: pool exhausted
T+48m02s              api-gateway   db_query       ConnectionPoolError: pool exhausted
... (844 more rows, all ConnectionPoolError, all api-gateway)

First error: T+48s  (47 minutes before pager)
```

The read: 847 `ConnectionPoolError` rows, every one of them from `api-gateway`, and the earliest is exactly 47 minutes old. The symptom is obvious — an exhausted pool. The start time is the lead worth chasing: something happened 47 minutes ago.

## Trace the change

Same journal, different table. Each VFS write is recorded with its timestamp, agent, path, and a content preview — so ask what was written during the 2 hours leading up to the errors:

```sql
SELECT timestamp, agent_id, file_path, content_preview
FROM vfs_events
WHERE timestamp > datetime('now', '-2 hours')
  AND event_type = 'write'
ORDER BY timestamp ASC
```

```text
elapsed               agent_id      file_path           content_preview
T+0                   api-gateway   config/db.yaml      ...pool_size: 2...
T+1s                  api-gateway   config/app.yaml     ...log_level: debug...
T+48s                 api-gateway   logs/error.log      ConnectionPoolError...
```

There it is: `config/db.yaml`, written under a minute ahead of the first error, with `pool_size: 2` visible in the preview.

## Prove it with a diff

Blobs in BENE are content-addressable, so comparing the pre-deploy checkpoint against the current state is a hash comparison plus two blob reads:

```diff
--- config/db.yaml (pre-deploy checkpoint)
+++ config/db.yaml (HEAD)
@@ -8,7 +8,7 @@
 database:
   host: postgres-primary.internal
   port: 5432
-  pool_size: 10
+  pool_size: 2
   pool_timeout: 30
   max_overflow: 5
```

A single line moved: `pool_size`, from `10` down to `2`. The write landed at 01:28:53; the first error followed at 01:29:41 — 48 seconds for production traffic to drain a 2-connection pool.

**Pager at 02:17:00. Cause confirmed at 02:17:24. Alert-to-root-cause: 12 seconds.**

## Fix forward, keep the evidence

Checkpoint the broken state before touching anything — the post-mortem will want it — then write the corrected config:

```text
bene checkpoint api-gateway --label broken-pool-size-2
# (preserved for post-mortem analysis)

# Apply the fix
bene write api-gateway /config/db.yaml \
  "$(cat config/db.yaml | sed 's/pool_size: 2/pool_size: 10/')"
```

Watch the recovery minute by minute:

```text
minute   errors
02:17    847
02:18    412
02:19     89
02:20     14
02:21      2
02:22      0  ✓
```

Five minutes from hotfix to a 0% error rate, down from the 23% peak.

## The post-mortem writes itself

Impact numbers come out of the same `tool_calls` table you started with:

```sql
SELECT
  COUNT(*)                                              AS affected_requests,
  MIN(timestamp)                                        AS outage_start,
  MAX(timestamp)                                        AS outage_end,
  ROUND(
    (JULIANDAY(MAX(timestamp)) - JULIANDAY(MIN(timestamp))) * 24 * 60, 1
  )                                                     AS duration_min
FROM tool_calls
WHERE status = 'error'
  AND agent_id = 'api-gateway'
  AND error LIKE '%ConnectionPoolError%'
```

```text
affected_requests   outage_start              outage_end                duration_min
4,847               T+48s                     T+53m10s                  52.4
```

4,847 failed requests over 52.4 minutes, all downstream of one config write at 01:28:53. The trigger, the first failure, every failure after it, and the recovery timestamp sit together in a single SQLite file — nothing to correlate across systems, nothing to reconstruct from memory.

## Where the 90 minutes went

Set the two workflows side by side:

```text
Traditional                        BENE
---------------------------------  -----------------------------------------
grep application logs (10 min)     SQL query over event journal (<1s)
check deploy system (5 min)        included in the same query
read git commits (5 min)           every VFS write is timestamped
ask the team (20 min)              not needed
correlate timelines (15 min)       ORDER BY timestamp ASC
```

Three properties of the journal account for the gap:

1. **Writes are journaled by default.** The moment `api-gateway` touched `config/db.yaml`, the event log gained a row carrying the timestamp, agent ID, and content — no instrumentation you had to remember to add.
2. **The log store is a SQLite table.** A timestamp-filtered SELECT comes back in milliseconds, with no aggregation service, no Elasticsearch cluster, and no parsing pipeline in the path.
3. **Blobs are content-addressable.** Diffing `pre-deploy` against `HEAD` means comparing hashes and fetching content — an exact one-line diff in under a second.

Nothing above required grep, deploy-system archaeology, or waking a teammate. Once each agent write enters a queryable append-only log from day one, the question every incident opens with has a standing answer.

## Keep going

- [README](../README.md) — BENE overview and full doc index
- [Use Cases](../use-cases.md) — more real-world patterns
- [Schema: events table](../schema.md#events) — the tables these queries read
- [Use case: 2am Incident Response](../use-cases.md#2am-incident-response) — the condensed version of this scenario
- [CLI: bene query / bene search](../cli-reference.md)

---

*BENE is MIT-licensed and local-first: every query on this page ran against one SQLite file on your own disk, and nothing was sent anywhere else.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
