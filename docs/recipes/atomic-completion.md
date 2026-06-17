# Recipe: atomic completion (exactly-once, ghost-free)

The densest cluster of P1 bugs in a long-running agent system is **non-atomic
completion**: a side effect (a receipt, a quota debit, a fork) happens, then the
process dies before the durable record is committed — leaving a **ghost** (an
external mutation no record knows about), a double-charge on retry, or an in-RAM
counter that evaporates on restart.

This is fixed with three substrate-agnostic moves on an ordinary SQLite/JSONL
log — **no Temporal, no durable-runtime dependency**. The reference helpers live
in `bene/recipes/idempotent_append.py`;
they take a `sqlite3.Connection`, not a `Bene`, so you copy them into your own
events layer.

## The three moves

1. **Idempotent append** — `SELECT` by `idempotency_key` then `INSERT`; the
   column is `UNIQUE`, so a replay (or a racer) is a no-op returning the prior
   id. Exactly-once.
2. **Ordering inversion** — commit the durable record *before* the externally
   visible side effect, then mark it done after the side effect returns. A crash
   then leaves either a completed row or a recorded pending row you can retry,
   never an orphan side effect with no record (a ghost).
3. **Projection rebuild** — on boot, fold the durable log to reconstruct in-RAM
   state, so a restart doesn't lose a volatile counter/cache.

## 1. Idempotent append

```python
import sqlite3
from bene.recipes.idempotent_append import ensure_log, append_once

conn = sqlite3.connect(":memory:")
ensure_log(conn)

seq, created = append_once(conn, "order-42:charge", {"amount": 100})
conn.commit()
# A replay with the same key is a no-op returning the prior id:
seq2, created2 = append_once(conn, "order-42:charge", {"amount": 100})
assert (created, created2) == (True, False) and seq == seq2
```

The `idempotency_key` column is `UNIQUE`, so even a racer that skips the `SELECT`
and inserts directly hits the database constraint instead of writing a duplicate.

## 2. Ordering inversion (no ghost)

```python
import sqlite3
from bene.recipes.idempotent_append import ensure_log
from bene.recipes.idempotent_append import complete_in_order

conn = sqlite3.connect(":memory:")
ensure_log(conn)
shipped = []

def ship_the_box(payload):
    shipped.append(payload["sku"])

# durable record commits FIRST, then the externally visible side effect
complete_in_order(conn, "order-42:ship", {"sku": "X"}, side_effect=ship_the_box)
assert shipped == ["X"]
```

`complete_in_order` appends + **commits** the record, then runs the side effect.
A crash after the commit leaves a recorded-but-pending completion you can
re-drive from the log; it can never leave a shipped box with no record. The
anti-pattern it replaces — `complete_side_effect_first` — does the mutation
before the commit, so a crash in between leaves a ghost (kept in the module only
as a labelled contrast).

If the process crashes *during* the external call, the helper will retry that
pending row later. Pass the same idempotency key through to the external system
or make the side effect safe to retry; a local log cannot make a non-idempotent
remote mutation exactly-once by itself.

## 3. Projection rebuild on boot

```python
import sqlite3
from bene.recipes.idempotent_append import append_once, ensure_log, replay_projection

conn = sqlite3.connect(":memory:")
ensure_log(conn)
append_once(conn, "charge-1", {"amount": 40})
append_once(conn, "charge-2", {"amount": 60})
conn.commit()

balance = {"total": 0}
replay_projection(conn, lambda key, payload: balance.__setitem__(
    "total", balance["total"] + payload["amount"]))
assert balance["total"] == 100
# `balance` is rebuilt purely from the durable log — no volatile state lost
# across restart (the restart-amnesia / `/replay` 404 class).
```

## Durability caveat — no Temporal needed

This recipe is **substrate-agnostic and adds no runtime dependency**. It gives
you exactly-once + ghost-free completion on whatever committed log you already
have (SQLite here; the same shape ports to a `flock`-serialized JSONL appender).

It does **not** add cross-process durability beyond your storage. In particular,
bene's `LocalRuntime` is explicitly *not* durable across restart, and
`submit_side_effect`'s fenced ledger only holds on `TemporalRuntime` (a stub in
most deployments) — so do **not** lean on the runtime for the durable record.
The committed log *is* the durable record, and that is the whole point: a plain
reorder + an idempotency key captures the large majority of the atomicity win
without taking on Temporal.

## See also

- `bene/recipes/idempotent_append.py` — the reference helpers.
- `tests/test_atomic_completion_recipe.py` — proves exactly-once + ghost-free under a simulated crash.
- [Integrating BENE](../integrating-bene.md) — where this sits among the five stages.
