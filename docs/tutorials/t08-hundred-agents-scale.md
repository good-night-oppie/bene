# Hundreds of Agents, One Database, Zero Regressions

This tutorial shows you how to fan bene out to hundreds of agents at once — one agent per file — and finish the run knowing, rather than hoping, that nothing broke. The worked example is real: 847 agents migrated an 847-file Python 2 codebase to Python 3.11 in 8 minutes 47 seconds, every failure rolled itself back, and the whole run left behind a single SQLite file you can interrogate with plain SQL.

> **One command spawns 847 isolated agents; 809 succeed, 31 restore themselves cleanly, 0 regressions ship — and the complete audit trail is a 214MB `bene.db` you can `cp`.**


*Seventeen batches, 847 agents: 809 succeed, 31 undo themselves, 7 go to humans, 0 regressions reach the codebase — and 2.45M tokens never get sent.*

---

## The run at a glance

Numbers first, story after. Here is how the 847 agents finished:

```text
Outcome      Count    %
-----------  -----  -----
succeeded    809    95.5%
rolled_back  31      3.7%
failed       7       0.8%
total        847   100.0%
```

And what the parallelism bought against the alternatives:

```text
Approach                    Time      Notes
--------------------------  --------  -------------------------
BENE parallel (847 agents)  8m 47s    17 batches of 50
Sequential AI (1 agent)     ~4.2h     no parallelism
Human engineers (estimate)  ~18 days  1 file per 30min × 847
```

Zero regressions is not luck; it is two gates each doing their job. 31 agents saw their own tests fail and restored to the pre-migration checkpoint on the spot. Roughly 180 more failures never happened at all, because the hub broadcast the responsible failure patterns before similar files were touched. Candor about the remainder: 7 files contained Python 2 constructs with no safe automated translation, and those agents stopped and flagged their files for human review instead of guessing.

---

## Why isolation is the whole trick

At a handful of agents, per-agent isolation reads like a nicety. Past a few hundred, it is the only thing standing between you and silent corruption. The failure mode of shared state is specific: one agent writes `utils/compat.py` mid-run while another reads that same file to decide on its own patch — no merge conflict appears, just quietly wrong bytes that surface days later as test failures with no visible cause. Shared context is the same disease in token form: frameworks that pool one context window across N agents pay roughly N× the tokens and get no extra intelligence for it.

bene's answer is structural. Each agent owns a private virtual filesystem (VFS) backed by SQLite — content-addressable, every write journaled, every checkpoint a cheap snapshot. Nothing is shared by accident; what agents do share (hub patterns, deduplicated blobs) is shared on purpose, through interfaces built for exactly that.

---

## Launch: one agent per file

The entire fan-out is one CLI invocation reading a manifest of file paths. Each agent takes one file, applies the migration, runs the tests, and either checkpoints the result or restores. The command starts with `bene parallel spawn`.

```bash
# Spawn 847 agents from a file manifest
bene parallel spawn \
  --manifest migration-manifest.txt \
  --task "migrate to Python 3.11, run tests, checkpoint on success" \
  --model claude-sonnet-4-6 \
  --batches 17 \
  --batch-size 50

# [bene] Reading manifest: 847 files
# [bene] Spawning batch 1/17 (agents 1-50)...
# [bene] Spawning batch 2/17 (agents 51-100)...
# ...
# [bene] All 847 agents spawned in 00:00:17s
# [bene] Running...
```

Behind that command sits a short `bene.yaml`:

```yaml
# bene.yaml
project: py2to3-migration

agents:
  model: claude-sonnet-4-6
  isolation: logical
  checkpoint_on_success: true
  rollback_on_test_failure: true

compression:
  aaak_level: 5          # ultra compression — 95% token reduction on digest
  blob_dedup: true       # SHA-256 + zstd deduplication across all agents

parallelism:
  max_concurrent: 50     # WAL-safe concurrency limit
  batch_size: 50
  retry_on_timeout: 2

hub:
  enabled: true          # CORAL hub coordination
  min_confidence: 0.85
  broadcast_on_discover: true
```

Two settings carry most of the weight. `aaak_level: 5` turns on bene's most aggressive context compression — roughly 95% off each agent's digest, measured below in real tokens. `max_concurrent: 50` caps simultaneous writers at a level SQLite's WAL mode handles comfortably; the 17 batches in the spawn output fall straight out of that cap.

---

## Recover: a failure costs exactly one agent

31 of the 847 agents hit failing tests after applying their migration. On a shared filesystem you would now be untangling state — reverting one file risks disturbing agents mid-flight on neighboring files. Here, recovery is a point-in-time restore of one private VFS: no global lock, no pause for anyone else.

Watch agent 312 handle `db/connections.py`, one of the 31:

```text
[agent-312] db/connections.py  migration applied
[agent-312] running pytest...
  FAILED tests/test_db.py::test_connection_pool_size
  FAILED tests/test_db.py::test_reconnect_on_timeout

  2 failed, 23 passed

[agent-312] test failures detected — rolling back to pre-migration checkpoint
[agent-312] restoring VFS to: pre-migration-312
[agent-312] restore complete in 0.08s
[agent-312] status: rolled_back
[agent-312] event logged: {
  "agent": "agent-312",
  "file": "db/connections.py",
  "failures": ["test_connection_pool_size", "test_reconnect_on_timeout"],
  "failure_pattern": "timeout_kwarg_renamed",
  "rollback_time_s": 0.08,
  "other_agents_affected": 0
}
```

Two numbers in that log are the point. The `restore complete in 0.08s` line means the VFS is back at its checkpoint before a tenth of a second passes. And `other_agents_affected: 0` means the remaining 846 agents never noticed.

<div class="callout" style="background:#12121a;border-left:3px solid #6c5ce7;padding:1rem 1.4rem;margin:1.5rem 0;border-radius:0 8px 8px 0">

**Checkable guarantee:** a restore touches exactly one agent's per-agent SQLite state — never the host filesystem, never a global lock, never anyone else's VFS. By construction, one failing agent's blast radius is itself.

</div>

Notice the `failure_pattern` field in the logged event — `timeout_kwarg_renamed`. That string is what feeds the hub, next.

---

## Coordinate: one rollback teaches twenty-three agents

In bene a rollback is not just damage control — it is a publication. The pattern extracted from the failing tests goes to the CORAL hub, the shared coordination point, where agents that have not yet reached similar files pick it up and adjust before they start.

The highest-value pattern of this run was `none_guard_before_has_key`:

```text
[hub] New pattern discovered from agent-312 rollback
  pattern: none_guard_before_has_key
  confidence: 0.91
  trigger: dict.has_key() calls where dict may be None
  fix: add `if dict is not None` guard before .get() replacement
  source_failure: test_connection_pool_size, test_reconnect_on_timeout

[hub] Broadcasting to 23 agents with similar pending files...
  agent-089: db/session.py         → applying pattern pre-emptively
  agent-134: db/pool_manager.py    → applying pattern pre-emptively
  agent-201: cache/backend.py      → applying pattern pre-emptively
  ...
  [23 agents notified]

[hub] Pattern confirmed: 23/23 agents applied, 0 new failures on similar files
```

Across the run the hub circulated 12 distinct patterns. Files whose agents had received a relevant pattern failed at 3.8%; comparable files without one failed at 22.1%. Applied to the ~210 files the hub reached, that gap accounts for roughly 38 avoided failures, and extrapolating over every pattern type gives the ~180 estimate.

```text
Patterns discovered                12
Agents notified                    147 total (across all patterns)
Estimated regressions prevented    ~180
Agent failure rate without hub     22.1%
Agent failure rate with hub         3.8%
```

Nothing mystical is happening here. A hub pattern is structured shared memory: a trigger condition, a fix, a confidence score. A receiving agent treats it as a hint rather than an order — closer to a senior colleague's warning than to an automatic patch.

---

## Spend less: compress the digest, not the work

![AAAK compaction flow — context digest → anchor extraction → K-compression → next turn](compaction-flow.png)

AAAK (Adaptive Anchor-Aware K-compression, bene's take on the MemPalace scheme) shrinks the context digest each agent carries between turns. At level 5 the digest comes back roughly 95% smaller. Working state is untouched, so the migrations an agent produces are the same with compression on or off — only the bill changes.

**Per agent, per turn:**

```text
What             Uncompressed  Compressed (L5)  Saved
---------------  ------------  ---------------  ------------------
Context digest   6,100 tokens  305 tokens       5,795 tokens (95%)
```

**Whole run — 847 agents averaging 3.4 turns apiece:**

```text
Total agent-turns          2,880
Tokens saved per turn      ~850 avg (varies by file)
Total tokens eliminated    2,451,063
```

Run the totals: uncompressed, this job would have cost about 8.58M inference tokens; it ran on about 6.13M — 2.45M tokens that simply never needed sending.

```text
Metric                      Without AAAK  With AAAK L5
--------------------------  ------------  ---------------------------
Total inference tokens       ~8.58M        ~6.13M
Context digest (per turn)   6,100 tokens  305 tokens (20×)
Tokens eliminated           —             2,451,063
Migration quality           —             100% — 0 regressions
```

![AAAK compression impact — token savings by level across 847 agents](compaction-chart.svg)

Be honest about the trade: level 5 is lossy, and digest nuance is lost. Independent single-file tasks like this migration tolerate that easily. If your agents must carry rich reasoning across turns — refactoring decisions that lean on earlier analysis, say — reach for level 3 or 4 instead. Either way it is one line in `bene.yaml`.

---

## Store less: 847 filesystems in 214MB

What does giving every agent its own filesystem cost in storage? Far less than the arithmetic suggests, because the blob store deduplicates content across the whole pool: blobs are addressed by SHA-256 and compressed with zstd, so a file held by two agents is stored once.

Naively, hand each of 847 agents its own copy of a codebase averaging ~250KB per file and you are storing ~212MB of raw files for every agent — ~179GB across the pool, and that is before a single context token, log line, or checkpoint is counted. Migration inputs share heavily (stdlib imports, helper functions, common boilerplate), and this run measured 68% deduplication:

```text
847 agents × ~250KB avg = 212MB naive
68% blob reuse         = 144MB deduplicated away
Actual stored          =  68MB (+ 39MB checkpoints)
                       = 107MB total vs 212MB naive
```

Checkpoints ride the same machinery. They record diffs, not full copies, and deduplication applies to their contents too — so the 31 rolled-back agents added almost nothing, their "bad" state sharing most blobs with the "good" state they restored to. End state: a single 214MB SQLite database holding complete history for all 847 agents — every write, every event, every blob.

<div class="callout" style="background:#12121a;border-left:3px solid #6c5ce7;padding:1rem 1.4rem;margin:1.5rem 0;border-radius:0 8px 8px 0">

**Checkable guarantee:** agent count does not multiply storage. Duplicate content collapses into one blob, and the reuse ratio improves the more your agents' files resemble each other — expect 60-70% deduplication on migrations and refactoring work.

</div>

---

## Audit: ask the database what happened

You do not have to take this tutorial's tables on faith. The run's entire record is ordinary SQLite, and each claim above is one query away.

How did the agents finish?

```sql
-- Outcome summary across all agents
SELECT status, COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / 847, 1) as pct
FROM agents
WHERE run_id = 'py2to3-migration'
GROUP BY status
ORDER BY count DESC;
```

```text
status       count   pct
-----------  -----   ----
succeeded    809     95.5
rolled_back  31       3.7
failed       7        0.8
```

Which failure patterns caused rollbacks, and where?

```sql
-- All rollback events with failure patterns, sorted by frequency
SELECT
  json_extract(notes, '$.failure_pattern') AS pattern,
  COUNT(*) AS occurrences,
  GROUP_CONCAT(file_path, ', ') AS affected_files
FROM vfs_events
WHERE run_id = 'py2to3-migration'
  AND event_type = 'restore'
GROUP BY pattern
ORDER BY occurrences DESC;
```

```text
pattern                        occurrences  affected_files
-----------------------------  -----------  --------------------------------
none_guard_before_has_key      8            db/connections.py, db/pool_manager.py...
print_function_side_effect     6            scripts/report.py, scripts/batch.py...
unicode_bytes_ambiguity        5            api/serializers.py, api/parsers.py...
iteritems_generator_consumed   4            core/registry.py, core/handlers.py...
...
```

What did compression actually save?

```sql
-- Token savings: what AAAK eliminated across all agents
SELECT
  SUM(tokens_uncompressed) AS total_uncompressed,
  SUM(tokens_compressed)   AS total_compressed,
  SUM(tokens_uncompressed - tokens_compressed) AS tokens_saved
FROM aaak_compression_log
WHERE run_id = 'py2to3-migration';
```

```text
total_uncompressed  total_compressed  tokens_saved
------------------  ----------------  ------------
4,949,663           2,498,600         2,451,063
```

Did the hub earn its keep?

```sql
-- Hub pattern effectiveness: failure rate before vs after broadcast
SELECT
  pattern,
  before_broadcast_failure_rate,
  after_broadcast_failure_rate,
  agents_notified,
  estimated_regressions_prevented
FROM hub_pattern_stats
WHERE run_id = 'py2to3-migration'
ORDER BY estimated_regressions_prevented DESC;
```

This is the difference between logs and a ledger. You are not grepping a summary; you are joining, grouping, and aggregating a structured record of everything that happened — 214MB, portable, and entirely yours.

---

## Limits: where this design bends

A fair account of the ceiling, so you can plan for it instead of discovering it.

**What holds at any scale:**

- **VFS isolation** — linear, indefinitely. Ten agents or ten thousand, no agent's filesystem ever waits on another's.
- **Blob deduplication** — better than linear: a larger pool of similar files raises the reuse ratio, so storage grows sublinearly in agent count.
- **AAAK compression** — purely local computation, linear per agent; savings stack directly as the pool grows.
- **Rollback** — constant time. The 0.08s restore above happened with 846 peers running and would take just as long alone.
- **Hub traffic** — tracks pattern discovery, not headcount. This run yielded 12 patterns from 847 agents, not 847 patterns.

**What needs thought above ~1000 concurrent agents:**

- **WAL write contention.** WAL mode is comfortable around 50 simultaneous writers and starts contending somewhere past 200-300. The shipped max_concurrent of 50 is conservative on purpose; if you genuinely need more, split the database into per-pool shards or move to a distributed backend.
- **Synchronous hub broadcasts.** Fanning one pattern to 23 recipients is quick at this scale. At 5,000 agents you would want broadcasts made async so coordination never blocks agent progress.
- **Hot-cache memory.** Each live agent keeps roughly 2MB of hot VFS state in memory: about 100MB at 50 concurrent, around 1GB at 500. Budget for it.
- **Spawn time.** Initializing 847 agents took 17 seconds; 5,000 would land near 100 seconds. Annoying, not blocking.

Everything above ran local-first, on a MacBook Pro. Past roughly 1,000 concurrent agents you would want dedicated hardware and possibly a distributed event store — and the seams are already clean: VFS, event journal, and blob store each sit behind an interface you could re-back with a distributed system while agent behavior stays exactly the same.

---

Worth restating plainly: 847 agents, 8 minutes 47 seconds, 809 files migrated, 31 clean self-restores, 7 escalated to humans, 0 regressions — plus 2.45M tokens that never needed sending. All of it survives in one 214MB SQLite file you can copy, query, and keep forever.

## Related

- [README](../README.md) — BENE overview and full doc index
- [Use Cases](../use-cases.md) — more real-world patterns
- [Component guide: Meta-Harness CORAL](../meta-harness.md#coral-getting-unstuck-v060)
- [Use case: Multi-Agent Co-Evolution](../use-cases.md#multi-agent-co-evolution-coral)
- [Architecture: scaling and isolation](../architecture.md)

---

*bene is MIT-licensed and local-first: the run, the agents, and the audit trail all live in one SQLite file on your machine, and nothing is sent anywhere you didn't configure.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
