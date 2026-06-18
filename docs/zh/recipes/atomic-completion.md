# 方案：原子化完成（Exactly-once 精确一次 · Ghost-free 无幽灵状态）

在长期运行的智能体系统里，P1 级严重漏洞最密集的温床莫过于非原子化完成。当某种副作用（例如打印收据、扣除额度、进程分叉）已经发生，而进程在持久化记录成功提交前突然崩溃，就会留下幽灵状态（即没有任何记录可查的外部变更）。这会导致重试时被重复扣费，或者内存中的计数器在重启后凭空蒸发。

要解决这一痛点，只需在普通的 SQLite 或 JSONL 日志上执行三个与底层技术栈无关的底层招式——完全无需引入 Temporal，也无需依赖任何持久化运行时。参考辅助函数位于 `bene/recipes/idempotent_append.py` 中；它们接收的是标准的 `sqlite3.Connection` 而不是 `Bene` 实例，因此你可以非常轻松地将它们复制到你自己的事件层中。

## 三大核心招式

1. **幂等追加（Idempotent append）** —— 先根据 `idempotency_key` 进行 `SELECT` 检查，若不存在再执行 `INSERT`。由于该列具有 `UNIQUE` 唯一性约束，任何重放操作或并发竞争都会变成无实质影响的空操作，并直接返回先前的 ID。由此实现 Exactly-once。
2. **顺序倒置（Ordering inversion）** —— 在执行任何外部可见的副作用之前，先提交持久化记录，并在副作用成功返回后再将其标记为已完成。这样一来，即使进程中途崩溃，数据库中也只会留下一条已完成的记录，或者一条已记录但仍处于待处理状态的行以供后续重试，而绝不会产生没有任何记录凭证的孤儿副作用（即幽灵状态）。
3. **投影重建（Projection rebuild）** —— 在系统引导启动时，通过折叠或遍历持久化日志来重新构建内存中的状态。这样，系统重启就不会丢失任何易失性的计数器或缓存。

## 1. 幂等追加

```python
import sqlite3
from bene.recipes.idempotent_append import ensure_log, append_once

conn = sqlite3.connect(":memory:")
ensure_log(conn)

seq, created = append_once(conn, "order-42:charge", {"amount": 100})
conn.commit()

# 使用相同的 Key 进行重放将是一次空操作，并返回之前的 ID：
seq2, created2 = append_once(conn, "order-42:charge", {"amount": 100})
assert (created, created2) == (True, False) and seq == seq2
```

由于 `idempotency_key` 列具有 `UNIQUE` 约束，即使某个并发竞争者跳过了 `SELECT` 检查而直接尝试插入，也会触发数据库约束异常，从而避免写入重复数据。

## 2. 顺序倒置（消除幽灵状态）

```python
import sqlite3
from bene.recipes.idempotent_append import ensure_log
from bene.recipes.idempotent_append import complete_in_order

conn = sqlite3.connect(":memory:")
ensure_log(conn)

shipped = []
def ship_the_box(payload):
    shipped.append(payload["sku"])

# 持久化记录首先进行提交，随后才执行外部可见的副作用
complete_in_order(conn, "order-42:ship", {"sku": "X"}, side_effect=ship_the_box)
assert shipped == ["X"]
```

`complete_in_order` 会先追加并提交记录，然后再运行副作用。在提交后发生崩溃会留下一条已记录但处于待处理状态的完成记录，你可以从日志中重新触发它；它绝不会导致货物已发出却无迹可寻的窘境。它所取代的反模式——先完成副作用（`complete_side_effect_first`）——是在提交前进行变更，因此其间的崩溃会留下幽灵状态（该反模式在模块中保留仅作为对比标签）。

如果进程在执行外部调用的过程中崩溃，辅助程序稍后会重试该待处理行。请务必将相同的幂等键透传给外部系统，或者确保该副作用本身具备可重试性；单凭本地日志是无法让一个非幂等的远程变更自发实现精确一次的。

## 3. 启动时的投影重建

```python
import sqlite3
from bene.recipes.idempotent_append import append_once, ensure_log, replay_projection

conn = sqlite3.connect(":memory:")
ensure_log(conn)

append_once(conn, "charge-1", {"amount": 40})
append_once(conn, "charge-2", {"amount": 60})
conn.commit()

balance = {"total": 0}
replay_projection(conn, lambda key, payload: balance.__setitem__("total", balance["total"] + payload["amount"]))
assert balance["total"] == 100
```

余额完全基于持久化日志重新构建——重启时不会丢失任何易失性状态（从而彻底告别重启失忆症或 `/replay` 404 这类典型问题）。

## 持久化警示——无需 Temporal

本方案与底层架构无关，且不增加任何运行时依赖。无论你当前使用何种已提交日志（此处以 SQLite 为例；相同的模式也可以轻松移植到通过 `flock` 序列化的 JSONL 追加器上），它都能为你提供精确一次且无幽灵状态的执行保证。

不过，它并不能在你的存储层之外凭空增加跨进程的持久性。特别是，BENE 的 `LocalRuntime` 在重启时明确是不具备持久性的，而 `submit_side_effect` 的隔离账本（Fenced ledger）仅在 `TemporalRuntime`（在大多数部署中只是个存根）上生效——因此，切勿将持久化记录的寄托押在运行时上。

已提交的日志本身就是那份不可磨灭的持久化记录，而这正是本方案的核心精髓所在：通过简简单单的顺序调整加一个幂等键，就能在不引入 Temporal 的情况下，斩获原子性所能带来的绝大部分红利。

## 参见

- `bene/recipes/idempotent_append.py` —— 参考辅助函数。
- `tests/test_atomic_completion_recipe.py` —— 在模拟崩溃下验证精确一次 + 无幽灵状态。
- [接入 BENE](../integrating-bene.md) —— 本方案在五个阶段中所处的位置。
