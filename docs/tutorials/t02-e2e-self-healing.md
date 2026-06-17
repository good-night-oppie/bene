# Undo an Agent's Bad Fix in 0.3 Seconds, Repo Untouched

This tutorial lets you give an agent a risky repair, watch the repair go wrong, and rewind that one agent to its pre-attempt state — while your checkout and every other running agent stay exactly as they were.

> **A checkpoint before each risky edit means a failed fix costs one command, not a lost morning.**

The loop you will follow: one red test, a plausible fix that turns it into four, a per-agent restore, a root-cause report the agent wrote about itself, and the repair that takes the suite to 47 green. Every transcript comes from the recorded run:


*The whole loop in one take: spawn, checkpoint, cascade to 4 failures, restore, root-cause report, correct fix, 47 green.*

## The trap: a red test that invites a cascade

A payment service has just refactored its `amount` field from `float` to `str` to keep API serialization consistent. CI reports a single failure:

```text
FAILED tests/test_payment.py::test_payment_decimal_precision
AssertionError: 10.00 != 10.0

Expected: Decimal('10.00')
Got:      10.0

1 failed, 46 passed in 3.2s
```

Precision bugs invite type-juggling repairs, and type juggling is where cascades begin: `float`, `Decimal`, and `str` each have their own ideas about equality, rounding, and JSON. A plausible one-liner here can multiply a single red test into four — leaving you chasing your own repair instead of the bug.

## Set up: give the failure a sandbox

Spawn a QA agent. It receives a full copy of the service inside its own SQLite-backed virtual filesystem (VFS) — a private workspace where breakage cannot reach your checkout or any sibling agent.

```text
bene spawn payment-qa --from ./payment-service

# [payment-qa] agent spawned  vfs_id=pqa-8f3a
# [payment-qa] running pytest...

FAILED tests/test_payment.py::test_payment_decimal_precision
  AssertionError: assert Decimal('10.00') == 10.0

  payment/models.py line 47:
    return float(self.amount)  # ← this line, post-refactor

1 failed, 46 passed
```

The red test now lives entirely inside `payment-qa`'s VFS. Nothing on your disk moved.

## Insure first: checkpoint the agent, not the repo

The agent's first action is not an edit — it is a snapshot. A checkpoint captures this one agent's full VFS at a moment in time, scoped to `payment-qa` and nobody else.

```text
bene checkpoint payment-qa --label pre-fix-attempt

# Checkpoint created: pre-fix-attempt
# Files snapshotted: 23
# VFS state: 1 test failing, 46 passing
# Timestamp: 2026-04-11T02:14:33Z
```

23 files, with the known-bad baseline (1 failing, 46 passing) on record. If the next edit goes sideways, recovery means returning this one agent to this label — no repo-wide reset, no collateral damage to agents mid-flight.

## Let it break: one failure becomes four

The first attempt is the one most engineers would reach for. The assertion wants `Decimal('10.00')`; the field returns something else; so coerce with `float()` and move on.

```python
# payment/models.py — agent's first attempt
def get_amount(self):
-   return self.amount
+   return float(self.amount)  # normalize to float
```

For money, that coercion destroys the very property the test protects: `float(Decimal('10.00'))` comes back as `10.0`, two decimal places gone. Four tests now fail where one did:

```text
FAILED tests/test_payment.py::test_payment_decimal_precision
FAILED tests/test_payment.py::test_payment_total_rounding
FAILED tests/test_payment.py::test_invoice_line_items_sum
FAILED tests/test_payment.py::test_refund_partial_amount

4 failed, 43 passed in 3.4s
```

The cascade is live. On an ordinary branch this is where the second guess gets committed on top of the first.

## Recover: rewind one agent in one command

```text
bene restore payment-qa --label pre-fix-attempt

# Restoring payment-qa to checkpoint: pre-fix-attempt
# Reverting 1 file: payment/models.py
# @@ -44,7 +44,7 @@
#  def get_amount(self):
# -    return float(self.amount)
# +    return self.amount
#
# Restore complete in 0.04s
# VFS state: 1 test failing, 46 passing (pre-fix state confirmed)
```

The restore finished in 0.04s and confirmed the baseline: back to 1 failing, 46 passing, exactly as checkpointed. Agents handling integration tests, documentation, and security scanning kept working through the entire rewind — isolation lives in the VFS rather than on the host filesystem, so with 4 agents up, one failing and recovering costs the other 3 nothing.

## Where git stops and the journal starts

| With git alone | With a bene checkpoint |
|---|---|
| `git reset --hard` rewinds the whole repository | `bene restore` rewinds one agent's VFS |
| `git log` records commits | the event journal records each file write, paired with the test run around it |
| `git stash` waits for a human to type it | agents checkpoint themselves ahead of each risky edit |
| `git bisect` hunts the breaking commit | one SQL query shows what the agent did at 02:14:41 that produced 3 new failures |

## Diagnose: the agent's own root-cause report

While the bad attempt was unraveling, the agent wrote a structured root-cause report into its VFS. The rewind reverted only `payment/models.py`, so the report is still there to read:

```text
bene read payment-qa /qa/failure_report.md

## Failure Analysis: test_payment_decimal_precision

Root cause: Precision loss in financial calculations.

The `amount` field uses `Decimal` for exact arithmetic. After the
refactor, `models.py` returns the raw field value which is now a
string ("10.00"). The test compares against Decimal('10.00').

String != Decimal. The equality check fails.

The wrong path: Converting to `float` loses mantissa precision.
float("10.00") == 10.0 — two decimal places lost, and float
arithmetic is not associative at scale.

Correct path: Decimal(str(amount)).quantize(Decimal('0.01'))
This preserves precision, handles string input, and passes IEEE 854
decimal arithmetic requirements for financial calculations.
```

Self-diagnosis, on the record: the report names the path that failed, names the path that will hold, and stays SQL-queryable for as long as the database exists.

## Repair: the fix that holds

Apply the path the report recommends:

```python
# payment/models.py — correct fix
from decimal import Decimal, ROUND_HALF_UP

def get_amount(self) -> Decimal:
    """Return amount as Decimal with 2dp precision."""
    return Decimal(str(self.amount)).quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP
    )
```

```text
tests/test_payment.py::test_payment_decimal_precision  PASSED
tests/test_payment.py::test_payment_total_rounding     PASSED
tests/test_payment.py::test_invoice_line_items_sum     PASSED
tests/test_payment.py::test_refund_partial_amount      PASSED
... (42 more)

47 passed in 3.1s
```

47 of 47 green, including the four the cascade took down.

## Verify after the fact: replay it from SQL

Each step above landed in bene's SQLite journal as it happened:

```text
Timestamp  Event       File                   Notes
---------  ----------  ---------------------  --------------------------------
02:14:29   spawn       —                      agent created, VFS initialized
02:14:31   tool_call   —                      pytest run: 1 fail, 46 pass
02:14:33   checkpoint  —                      label: pre-fix-attempt
02:14:41   write       payment/models.py      attempt: float() cast
02:14:43   tool_call   —                      pytest: 4 fail — cascade
02:14:44   write       /qa/failure_report.md  root cause diagnosed
02:14:45   restore     —                      restored to pre-fix-attempt
02:14:52   write       payment/models.py      Decimal.quantize() fix applied
02:14:54   tool_call   —                      pytest: 47 pass
```

From the spawn at 02:14:29 to the green run at 02:14:54, every write, rewind, and pytest invocation is timestamped and queryable. Git history answers which lines changed; the journal answers which test run provoked which edit. If the loop ran overnight, this table reconstructs it at breakfast — down to the write that started the cascade and the restore that unwound it.

## Keep going

- [Component guide: Checkpoints](../checkpoints.md) — snapshot and restore mechanics in depth
- [Audit trail SQL: events table](../schema.md#events) — query the journal yourself
- [Use case: End-to-end Self-Healing CI](../use-cases.md#end-to-end-self-healing-ci) — this pattern in the catalog
- [Use Cases](../use-cases.md) — more recovery and orchestration patterns
- [README](../README.md) — the full doc map

---

*bene is MIT-licensed and runs entirely locally; nothing is sent anywhere.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
