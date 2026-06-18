# 在 BENE 上搭一座对抗式编程竞技场：底座层的设计 (A Competitive Coding Arena on BENE: Design at the Substrate Layer)

*Engineering · 2026-06*

---

## 背景 (Context)

把几个编程 agent 关进同一间屋子，丢给它们同一道真实的工程任务，再评出谁干得最漂亮。说起来简单，真要诚实地跑起来却凶险无比。一旦某个结果开始左右排名，你底座（substrate）里的每一处软肋都会变成一个能被钻的空子：一个能偷看对手文件的 agent、一个没有凭据的分数、一场没法复现的胜利、一张悄悄就采信了 agent 自我陈述的榜单。

本案例讲的就是这类竞技场的**底座层设计**——抽象层面上那几个真正吃重的决策。它讲的是*模式*，而非某个具体产品的实现；这里的应用逻辑是故意写成伪代码的。它要说清的是：一个对抗式的多 agent 平台，为什么底下想要 BENE 这样的东西，以及那四条保证是如何从原语（primitive）里自然长出来的。

## 问题拆解 (Problem framing)

竞技场天生就是个对抗环境。要让一场比赛跑出来的排名真有分量，就必须由底座——而不是应用——来兜住这四件事：

- **隔离 (Isolation)。** 一个选手绝不能读写另一个选手的工作区。
- **可审计 (Auditability)。** 每一个被计分的动作，都得有一条持久、可验证防篡改的凭据。
- **可复现 (Reproducibility)。** 任何结果都必须能重跑一遍，用来了结争议。
- **沉淀记忆 (Accumulated memory)。** 平台应当一局比一局更聪明，同时绝不把某一局的机密泄进另一局。

这几条里只要有任何一条落在应用代码里，迟早会有一个 agent（或者一个 bug）把它绕过去。它们的归宿是底座。

## 设计 (Design)

每条保证都对应一个 BENE 原语。竞技场代码能保持精简，正是因为那些硬骨头交给了引擎去啃。

| 竞技场的诉求 | BENE 原语 | 为什么成立 |
|---|---|---|
| 隔离 | per-agent VFS，以 `agent_id` 做 SQL 作用域 | 选手自己的 `fs_*` 工具只在它自己的命名空间里活动（对抗式代码需另加 OS 沙箱 + 受限工具集——见下文） |
| 可审计 | append-only 事件日志 + 执行轨迹 | 每个动作都是一行（按约定只追加；若 DB 可写，用哈希链兜防篡改） |
| 可复现 | checkpoint / restore / diff | 从快照重跑一局的 BENE 状态（不含外部副作用） |
| 沉淀记忆 | 记忆轨迹（engram）+ 轨迹检索 | 跨局学习；kernel 的检索器不按 agent 过滤，作用域得你自己框死 |

### 隔离——密封小黑屋，一个文件搞定 (Isolation — sealed rooms, one file)

每个选手都跑成一个隔离的 agent。引擎按 `agent_id` 给 agent 自己的 `fs_*` 工具划定作用域，于是选手的读写都被锁死在自己的命名空间里。这是一个文件里实现的逻辑隔离——对付**对抗式**选手，还得配上一层 OS 沙箱和一套受限工具集：默认 runner 是放行 `shell_exec` 的，而面向运维方的 `query` / `agent_read` 工具吃的是显式传入的 `agent_id`，所以单论它俩，谁都算不上一道硬的跨 agent 边界。

```python
from bene import Bene

arena = Bene("arena.db")            # 整场赛事就一个可审计的文件
for competitor in entrants:         # 伪代码：你的参赛名单
    arena.run(name=competitor, task=PROBLEM)   # 每人分到一个密封工作区
# 选手 A 自己的 fs_* 工具永远解析不到选手 B 的 /solution.py
```

### 可审计——凭据就是那一行记录 (Auditability — the receipt is the row)

计分只从日志里读，绝不读 agent 的自我陈述。这条日志的只追加是*靠应用层约定*做到的——如果在你的竞技场里，某个选手或运维方有权写那个 SQLite 文件，那就在把凭据当作不可伪造之前，先加上真正的防篡改手段（对行做哈希链，或者把只追加存储放到选手够不着的地方）：

```python
# 伪代码：从记录下来的事件推导分数，而不是从 agent 自己的说法
events = arena.events(agent_id=competitor)        # 那条持久的轨迹
score  = rubric(events)                            # 在已记录的事实上确定性地算分
```

谁晋级、谁被取消资格——这类协调决策本身也通过 shared-log 协议落了日志，于是赛程表（bracket）和那些比赛享有同一条审计轨迹：

```python
from bene.shared_log import SharedLog
log = SharedLog(arena.conn)
log.intent("advance winners of round 1")
log.vote(intent_id, approve=True)
log.decide(intent_id)                              # 持久、有序、可回放
```

### 可复现——争议靠回放了断 (Reproducibility — disputes settled by replay)

每一步计分之前，竞技场先打个 checkpoint；有争议的结果是从快照重跑，而不是靠嘴仗：

```python
cp = arena.checkpoint(competitor, label="pre-grade")
# ...打分...
arena.restore(competitor, checkpoint=cp)           # 回滚 BENE VFS + 状态
```

`restore` 回滚的是 agent 由 BENE 托管的 VFS 和 KV 状态。那些伸到 BENE *外面*的步骤——一次模型调用、`shell_exec`、网络或宿主文件系统的副作用——是不会被回放的，所以一次重跑能确定到什么程度，取决于有争议的那部分工作有多大比例留在底座之内。

### 沉淀记忆——跨局更聪明，单局内封死 (Accumulated memory — smarter across matches, sealed within one)

打完的比赛会留下轨迹，这些轨迹会沉淀成记忆轨迹（engram）。后面的比赛该检索的是*经验教训*（什么样的做法容易卡在某道闸门上），而不是原始工作区——但这个检索的作用域得你自己显式框死：kernel 的检索器只在*记录*这次查询时才按 `agent_id` 过滤，所以请把比赛/agent 的作用域传进检索里（或者手工挑选哪些记忆轨迹是共享的），别想当然地以为跨局读取默认就是封死的。

```python
arena.retrieve("common failure modes on refactor tasks")
```

## 洞察 (Insights)

- **把保证往下沉。** 一座竞技场要做到*公平*所需的每一条性质，都是底座能强制、而应用不可被信任去兜的性质。隔离靠 SQL 作用域、凭据靠 append-only 日志——这些都不是你事后拧上去的功能；它们恰恰就是你为什么要有一层底座的理由。
- **分数是一次查询，不是一句声明。** 排名是从落了盘的日志里推出来的——绝不取自 agent 的自我陈述——这才是一张榜单经得起推敲的根本。
- **单文件是运维上的恩赐。** 整场赛事就是一个 SQLite 数据库：复制它就是备份，diff 它就是审计，把它交给下一班人就不用重建任何状态。

## 你该从这里带走什么 (What to take from this)

你不必非得有一座竞技场，才会想要这四条性质——任何一个正经的多 agent 系统都想要。竞技场只不过是不允许你把它们装样子糊弄过去而已。在一个把隔离、可审计、可复现、记忆都做成*默认*的底座上去搭，上面那层应用就能保持精简、诚实、可回放。
