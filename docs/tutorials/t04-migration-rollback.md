# Roll Back a Bad Migration in 0.3 Seconds

Run a risky migration with an undo button: when a 2-million-row backfill went bad mid-stream, one command erased the damage in 0.31 seconds, and no other agent noticed.

> **One checkpoint before the risky phase turns a 2-million-row mistake into a 0.31-second fix.**


*Checkpoint after phase 1; the phase-2 backfill pauses itself on a NULL anomaly at row 847,412; restore in 0.3s; analytics agents keep running.*

## Start with the payoff: the restore

The backfill had written 64,412 bad NULLs into `subscription_tier` before the agent paused itself. Recovery was one command against a labeled checkpoint:

```text
bene restore migration-agent --label pre-backfill

# Restoring migration-agent to checkpoint: pre-backfill
#
# Changes reverted:
# --- migration/state.json
# -  "phase": "backfill",
# -  "rows_processed": 847412,
# -  "null_count": 64412,
# -  "status": "anomaly_paused"
# +  "phase": "schema_complete",
# +  "rows_processed": 0,
# +  "status": "ready_for_backfill"
#
# Restore complete in 0.31s
```

0.31 seconds, and the agent's virtual filesystem (VFS) — the private workspace every bene agent runs in — is back at a known-good point; everything the failed phase wrote is gone. The rest of this page replays the run behind that one-liner.

## The plan behind the run

The job: add `subscription_tier` — the column deciding what each user can access — to a `users` table of 2 million rows. Three phases, a checkpoint boundary after each, an anomaly check armed on the dangerous one:

```python
# migration/add_subscription_tier.py

PHASES = [
    {
        "name": "schema_change",
        "sql": "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20)",
        "checkpoint": "pre-backfill"
    },
    {
        "name": "backfill",
        "sql": """
            UPDATE users
            SET subscription_tier = s.tier
            FROM subscriptions s
            WHERE users.id = s.user_id
        """,
        "batch_size": 10_000,
        "anomaly_check": True,
        "checkpoint": "pre-constraint"
    },
    {
        "name": "enforce_constraint",
        "sql": "ALTER TABLE users ALTER COLUMN subscription_tier SET NOT NULL",
        "checkpoint": "complete"
    }
]
```

Two analytics agents, `analytics-agent-1` and `analytics-agent-2`, query this data throughout. Each owns a separate VFS, so interference is structurally impossible.

## Checkpoint before you touch data

Phase 1 is the cheap, reversible part — an `ALTER TABLE` that changes no rows. Run it, then pin the moment with a label:

```text
bene run migration-agent "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20)"

# [migration-agent] schema change: SUCCESS
# [migration-agent] 2,041,847 rows will be updated in Phase 2

bene checkpoint migration-agent --label pre-backfill

# Checkpoint created: pre-backfill
# Phase 1 state: schema applied, no data changes yet
# Timestamp: 2026-04-13T01:33:11Z
```

That label is the whole insurance policy. The rollback actor is `migration-agent`; whatever the backfill does, `bene restore migration-agent --label pre-backfill` brings the agent back here: schema in place, zero rows changed, ready for another attempt.

## The backfill stops itself

Phase 2 streams updates in 10,000-row batches while the anomaly check samples the NULL count every 50K rows. The log stays clean until row 847,412:

```text
[backfill]  100,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  200,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  300,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  500,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  700,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  847,412 rows processed  NULL count: 64,412 (7.6%)  ✗

ANOMALY DETECTED: NULL rate 7.6% exceeds threshold 0.0%
Expected: 0 NULLs in subscription_tier
Got:      64,412 NULLs out of 847,412 rows processed

Migration PAUSED. No further rows updated.
```

No human watched for this. The agent froze the run on its own — a 7.6% NULL rate can never satisfy the NOT NULL constraint waiting in phase 3.

## The diagnosis was already written

Before pausing, the agent left a root-cause report in its own VFS. Reading it costs one command:

```text
bene read migration-agent /logs/anomaly.md

## Anomaly Report: subscription_tier NULL at 7.6%

First NULL detected: user_id 8,042,183 (batch 84 of 205)
Pattern: All NULL users share a creation date before 2021-03-15

Root cause: Legacy users who registered before the subscriptions
table existed have no row in the `subscriptions` table.
The JOIN returns NULL for these users.

Fix: Use COALESCE to default unmatched users to 'free':
  UPDATE users
  SET subscription_tier = COALESCE(s.tier, 'free')
  FROM subscriptions s
  WHERE users.id = s.user_id

Estimated affected rows: ~156,000 legacy users (pre-2021-03-15)
```

Every NULL belongs to an account created before 2021-03-15 — older than the `subscriptions` table itself, so the JOIN finds nothing to match. The repair is a single `COALESCE`.

## A clean second pass

Restore (shown above), apply the `COALESCE` default, rerun. Same plan, same batch size, different ending:

```text
[backfill]  500,000 rows   NULL count: 0  (0.0%)  ✓
[backfill]  1,000,000 rows NULL count: 0  (0.0%)  ✓
[backfill]  1,500,000 rows NULL count: 0  (0.0%)  ✓
[backfill]  2,000,000 rows NULL count: 0  (0.0%)  ✓
[backfill]  2,041,847 rows NULL count: 0  (0.0%)  ✓ COMPLETE

[phase 3]  ALTER TABLE users ALTER COLUMN subscription_tier SET NOT NULL
[phase 3]  SUCCESS — constraint enforced on 2,041,847 rows

Migration complete. Duration: 47m total (including rollback + retry).
```

47 minutes wall-clock, failed attempt and rollback included.

## Check the blast radius yourself

Isolation is a claim you can verify, not a promise to trust. The fleet, immediately after the restore:

```text
bene ls

# NAME                STATUS    UPTIME   EVENTS
# migration-agent     restored  14m      847 (rollback applied)
# analytics-agent-1   running   14m      1,204
# analytics-agent-2   running   14m      983
# dashboard-agent     running   14m      441
```

Three unrelated agents, zero interruptions. Each works in its own SQLite-backed filesystem, so the migration's half-finished state was never visible to them — and after the restore it exists nowhere.

## Replay the whole incident

The full run reads back as one timeline — spawn, checkpoints, anomaly, restore, fix, clean finish:

```text
Time      Event       Phase               Rows       NULLs   Notes
--------  ----------  ------------------  ---------  ------  --------------------------------
01:33:08  spawn       —                   —          —       agent initialized
01:33:11  checkpoint  pre-schema          0          0       label: pre-schema
01:33:14  schema      schema_change       0          0       ALTER TABLE: success
01:33:16  checkpoint  pre-backfill        0          0       label: pre-backfill
01:33:18  backfill    backfill            847,412    64,412  anomaly: 7.6% NULL
01:34:01  restore     —                   0          0       restored to pre-backfill (0.31s)
01:34:04  fix         —                   —          —       COALESCE applied to query
01:34:06  backfill    backfill            2,041,847  0       full backfill: 0 NULLs
02:21:14  constraint  enforce_constraint  2,041,847  0       NOT NULL enforced
02:21:17  checkpoint  complete            2,041,847  0       migration complete
```

Without the mid-stream check, your first signal is a user bug report the next morning, after corrupt values ship. With it, the bad rows never left one agent's workspace, and erasing them took 0.3 seconds.

## Keep reading

- [Component guide: Checkpoints](../checkpoints.md)
- [Use case: DB Migration Rollback](../use-cases.md#db-migration-rollback)
- [Use Cases](../use-cases.md) — more patterns like this one
- [Architecture: VFS engine](../architecture.md)
- [README](../README.md) — overview and full doc index

---

*bene is MIT-licensed and local-first: every command on this page ran on one machine, and no data left it.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
