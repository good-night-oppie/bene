# 菜谱：原子化完成 (atomic completion) — 精确一次执行，杜绝“幽灵”副作用

在一个长时间运行的 Agent 系统里，最致命的 P1 级连环 Bug 通常源自**非原子化的完成操作 (non-atomic completion)**：副作用（比如生成一张收据、扣减一次配额、或者派生一个分支）已经发生，结果进程却在把这条持久化记录提交落盘前暴毙了 —— 这会留下一个**幽灵 (ghost)**（外部状态变了，但没有任何记录察觉），或是在重试时触发双重扣费，又或是让那些存在内存里的计数器随着一次重启直接灰飞烟灭。

解决这个问题，不需要请出 Temporal 或任何持久化运行时依赖。我们只需在一个普普通通的 SQLite 或 JSONL 日志上耍三招底层的**无依赖通杀技 (substrate-agnostic moves)**。相关的参考代码在 `bene/recipes/idempotent_append.py` 里；它们吃的是 `sqlite3.Connection` 而不是 `Bene` 实例，所以你大可以把它们整碗端进你自己的事件层里。

## 三板斧

1. **幂等追加 (Idempotent append)** — 先按 `idempotency_key` 执行 `SELECT`，没有再 `INSERT`；因为该列被设为 `UNIQUE`，所以任何重播（或者并发的竞争者）都会变成一次安全空转，并乖乖返回之前生成好的 ID。这就是**精确一次 (Exactly-once)** 的保证。
2. **顺序倒置 (Ordering inversion)** — **先**把持久化记录提交落盘，**再**把副作用释放到外部去，等副作用回调后再把记录标记为已完成。这样一来，即使发生崩溃，留下来的要么是一条干干净净的已完成记录，要么就是一条等着你重试的挂起记录——绝不会凭空冒出一个毫无案底的幽灵副作用。
3. **拉起时的投影重建 (Projection rebuild)** — 每次开机时，把那卷持久化日志从头到尾盘一遍，借此把内存状态（比如缓存或计数器）重塑出来，这样重启操作就再也别想偷走任何易失性数据了。

## 1. 幂等追加

```python
import sqlite3
from bene.recipes.idempotent_append import ensure_log, append_once

conn = sqlite3.connect(":memory:")
ensure_log(conn)

seq, created = append_once(conn, "order-42:charge", {"amount": 100})
conn.commit()
# 如果用同一个 key 再重播一次，它只会是一次返回之前 ID 的空转：
seq2, created2 = append_once(conn, "order-42:charge", {"amount": 100})
assert (created, created2) == (True, False) and seq == seq2
```

`idempotency_key` 这个字段被上了 `UNIQUE` 锁，所以哪怕是个直接绕过 `SELECT` 强行塞数据的并发疯子，也会被数据库的约束机制无情拍飞，绝对写不进重复的账条。

## 2. 顺序倒置 (告别幽灵副作用)

```python
import sqlite3
from bene.recipes.idempotent_append import ensure_log
from bene.recipes.idempotent_append import complete_in_order

conn = sqlite3.connect(":memory:")
ensure_log(conn)
shipped = []

def ship_the_box(payload):
    shipped.append(payload["sku"])

# 先让持久化记录落盘 COMMIT，然后才触发对外可见的副作用
complete_in_order(conn, "order-42:ship", {"sku": "X"}, side_effect=ship_the_box)
assert shipped == ["X"]
```

`complete_in_order` 的逻辑是追加记录 + **马上 COMMIT**，然后再去触发那个副作用。如果 COMMIT 刚完进程就死了，你至少能从日志里捞出那条“已记录但未完结”的账，然后从头再驱动一次；这总比丢出一个没有任何案底的箱子要强得多。而被它干掉的反模式 —— `complete_side_effect_first` —— 则是先干脏活再 COMMIT，这两步之间的任何一次断电都会催生出一个幽灵（这个反面教材还留在模块里，专作反面教材之用）。

如果进程死在外部调用的**途中**，那么这个帮手函式稍后会把这行挂起的记录拿出来重试。因此，请务必把你的幂等键 (idempotency key) 一并传给那个外部系统，或者确保这个副作用本身经得起反复碾压；毕竟，光靠一个本地日志，是没法把一个不具备幂等特性的远程突变魔法般地变成“精确一次”的。

## 3. 开机时的投影重建

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
# `balance` 纯粹是靠着持久化的日志一笔一笔重塑出来的 —— 跨越重启，无一分易失状态丢失。
# (这就是专门用来治那类所谓的“重启失忆症 / `/replay` 报 404” 顽疾的配方)。
```

## 耐久性警语 —— 不需要 Temporal

这个菜谱是**与底层无关的，且不会引入任何运行时依赖**。只要你手头上有一个支持提交特性的日志系统（在这里是 SQLite；同样的打法你完全能无缝搬到一个用 `flock` 上锁的 JSONL 追加器上），它就能赋予你“精确一次”外加“无幽灵”的完成保障。

但请记住，它**不能**提供超越你存储介质本身的跨进程耐久度。尤其是，BENE 的 `LocalRuntime` 已经挑明了**不具备**跨重启的耐久性，而 `submit_side_effect` 那本带护栏的账本也只有在用上了 `TemporalRuntime`（目前在大多数部署里都只是个占位符）时才作数 —— 所以，**千万别**指望运行时能帮你兜底持久化记录。这本提交过的日志**本身**才是那条持久化生命线，而这正是整套拳法的精髓所在：只消做个简单的时序倒置，外加一把幂等锁，你就能在不碰 Temporal 这尊大佛的前提下，把绝大把的原子化收益稳稳装进口袋。

## 延伸阅读

- `bene/recipes/idempotent_append.py` — 包含参考用法的帮手函式。
- `tests/test_atomic_completion_recipe.py` — 通过模拟崩溃，证实了精确一次 + 无幽灵机制的靠谱程度。
- [集成 BENE (Integrating BENE)](../integrating-bene.md) — 看看这套招式在那五个落地阶段里到底能排老几。
