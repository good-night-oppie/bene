# 将代码生成 (Code Generation) 作为 BENE 的核心能力

**状态：** 提案方向，尚未实装。请参考本文档末尾的验证性实验。

---

## 这份提案想干嘛

BENE 的一项未来能力：吃进一段任务描述，然后直接吐出一套完整、能跑的实现代码 —— 并且这套代码会精准地使用 BENE 的运行时抽象层作为它的目标中间表示 (IR, Intermediate Representation)。

在抽象意义上，这并不是个什么横空出世的新功能。它只是把现有的 BENE 积木（CCR、技能系统、元引擎、基于调用链的 RAG、VFS 结界、存盘快照）拼起来，去死磕一种极致的用户体验：**让用户只用大白话聊业务逻辑；让 BENE 去徒手捏那些折磨人的 Temporal 底层和分布式系统代码。**

---

## 为什么这事生死攸关

大多数拿 BENE 去干活的人（不管是拉起特种兵军团、逆转时空读档、拿 SQL 查水表、还是跑元引擎进化），压根就不需要知道 Temporal、`signal_with_start` 是什么鬼，或者去关心什么劳什子的工作流确定性约束 (determinism)。他们拿本地的 SQLite 就能玩得很嗨。详情去看 [用例地图 (use-cases.md)](use-cases.md)。

但是，有一小撮但在不断壮大的核心玩家 —— 那些搞实体 Actor (entity actors)、跑持久化状态工作流、攒基于时间窗的水桶 (time-bounded buckets)、做请求收敛去重 (request coalescers) 的人 —— 是真刀真枪地需要把手伸进 `bene/temporal/` 引擎里的。生产环境里的第一个苦逼吃螃蟹者，就是 triage-rag 项目 L3 管道里的那个突发警报聚合器 (burst aggregator)。

对于这帮人来说，从 "我有个业务需求" 到 "我写出了一段能扛住炸机的持久化代码" 之间，横着一道令人绝望的天堑：

1. 得生啃 Temporal 的概念大山 (Workflow, Activity, TaskQueue, RetryPolicy)
2. 得搞懂确定性 (determinism) 约束到底是个什么反人类的东西
3. 得摸透 signal/query/start 这三把板斧的语义
4. 为了这一个在概念上极其简单的玩意，得徒手糊 50 多行的下水管道代码 (plumbing)

代码生成 (Codegen) 就是为了把这条天堑给夷平的。

---

## 藏头露尾的三层架构

| 层次 | 归谁管 | 替你藏了什么恶心东西 | 露给你看什么 |
|-------|-------|-------|---------|
| **L1: 抽象层** | `bene/temporal/` 的维护者 | 竞态安全 (Race safety)、重放安全 (replay safety)、幂等性死律 | 高级原语 (`start_or_signal`, `query`, `signal`) |
| **L2: 生成层** | BENE 生成器 + 技能系统 (skills) | 工作流的骨架、Activity 注册、重试策略、测试脚手架 | 塞满了业务逻辑占位符的生成代码 |
| **L3: 业务逻辑层** | 你 (用户) | （啥也不藏 —— 这是你的地盘） | 领域规则：具体的函数逻辑、去重策略、到底什么才算是一个 "重复" 事件 |

每一层都在死死捂住它的下游不该操心的事情，同时把下游该操心的事情赤裸裸地暴露出来。

**为什么 L1 和 L2 缺一不可：**

- 没了 L1，生成的代码就是一坨赤裸裸的 Temporal SDK 原生调用。你根本看不懂这堆天书、不敢在不懂 Temporal 的情况下瞎改、甚至连框架升级都别想沾边。这就是所谓的 Yeoman 模板陷阱：每一次生成，就是一次与主线代码的分道扬镳。
- 没了 L2，每个用它的人都得徒手去手写那 50 行的包装纸。抽象层虽然好用，但没人去用。
- 两者合璧，用户只要专心写那 5 行业务逻辑。生成器会用一套极其稳定的原语去帮你把恶心的胶水代码全糊好。抽象层负责把那些史无前例的坑全给填了。

---

## 它的靶子是中间表示 (IR)，绝不是裸写的 Temporal

在边界设计文档里的那些基础原语 (`start_or_signal`, `business_idempotency_key`, `side_effect_label`) 绝对不是什么只为了运行时少写两行代码的语法糖。它们是专门为代码生成层定制的**目标中间表示 (IR)**。

它吐出来的代码长这样：

```python
handle = await runtime.start_or_signal(
    spec=BurstBucketSpec(bucket_id=bucket_id, ttl=delta_burst),
    signal_name="event",
    payload={"event_id": event.id},
)
```

绝不会是这种画风：

```python
client = await temporal_client.connect()
try:
    handle = await client.start_workflow(
        BurstBucketWorkflow.run,
        ...,
        id=bucket_id,
        task_queue="burst-buckets",
        execution_timeout=timedelta(seconds=delta_burst * 2),
    )
except WorkflowAlreadyStartedError:
    handle = client.get_workflow_handle(bucket_id)
await handle.signal("event", {"event_id": event.id})
```

第一种你能像看大白话一样看懂、能放心改、框架升级了它照样能跑。第二种就是你现在每天都在苦逼手敲的那堆东西。

---

## 怎么把 BENE 现有的破铜烂铁拼成神装

| BENE 现有能力 | 在代码生成里扮演什么角色 |
|---|---|
| **元引擎 (Meta-harness)** | 专门负责去进化那套 "任务描述 → 架构决策" 的映射关系 |
| **技能系统 (Skills system)** | 存着那些可复用的骨架模板 ("实体 Actor 脚手架", "定时任务脚手架") |
| **基于调用链的 RAG** | 跑去数据库里捞 "上次那个长得差不多的玩意是怎么干的" —— 让生成的代码脚踏实地踩在被验证过的实盘记录上，而不是纯靠大模型的脑补 |
| **CCR + Claude** | 真正坐在那里疯狂敲键盘的干活苦力 |
| **边界抽象原语** | 它的终极靶心 (IR)；也是生成器唯一被允许吐出的动词 |
| **VFS 结界** | 每一波生成都在自己的沙盒里试毒；写崩了的废稿绝对不会弄脏你的主库 |
| **快照 (Checkpoints)** | 不爽就一键删档重写；你甚至能把几次不同思路的产物拿来做 diff |

这就极其符合 "必须靠进化引擎 (harnesses) 吃饭，而不是去赌大模型运气" 的核心信条。代码生成本身就是一个引擎；而元引擎会随着时间慢慢把它盘出包浆来。

---

## 别装逼，有这几条硬伤

1. **Temporal 代码早就超出了现在 LLM 的智商边界。** 确定性 (Determinism)、重放安全、信号 vs 查询的语义偏差 —— 这些破规矩跟这世界上绝大多数人写异步代码的习惯是完全背道而驰的。第一把吐出来的代码绝对是废品，必须靠一轮轮的测试反馈把它抽到及格。
2. **生成的代码必须打死标记 (marker)。** 一旦用户进去改了那些自动生成的代码，下次再生成时就极容易把他们的心血给抹了。生成器必须极其老实地打上 `BUSINESS_LOGIC_BEGIN` 和 `BUSINESS_LOGIC_END` 的路标，并在重新生成时死死护住这两块路标中间的东西。
3. **抽象层没落地，生成器就是个瞎子。** 这个前置条件现在已经扫清了：运行时的边界原语 (`start_or_signal`, `submit_side_effect`, `SideEffectLabel`, `BusinessIdempotencyKey`, `CostEstimate`) 以及 `LocalRuntime` 和 `TemporalRuntime` 已经在 `bene/runtime/` 和 `bene/temporal/runtime_impl.py` 里实装了，IR 有了能真正落地的靶子。现在剩下的唯一缺口是 L2 的生成层本身 (比如那个 `EntityActor` 基类)，而不是它依赖的地基。
4. **代码生成救不了不学无术。** 如果用户这辈子都没去扫一眼那些生成的代码，等生产环境炸机时他们就只能干瞪眼。L2 这层遮羞布盖住的是 "你不用亲手去写这段苦力活"，而不是 "你可以对它一无所知"。

---

## 未来的 L2 战斧 (等 IR 彻底不折腾了再说)

第一次跑去趟这浑水 (2026-05-04，在 L3 警报聚合器上做实验) 后，我们被狠狠打脸了：生成的代码在 **Activity 层面** 上能做到对 IR 的绝对纯净，但是在 **工作流类 (workflow class)** 层面，还是无可救药地漏出了一堆 Temporal 专属的装饰器：

```python
@workflow.defn
class BurstBucketWorkflow:
    @workflow.signal(name="event")
    async def handle_event(self, payload: dict[str, str]) -> None: ...
    @workflow.query(name="seed_ticket")
    def seed_ticket(self) -> str | None: ...
    @workflow.run
    async def run(self, spec: BurstBucketSpec) -> dict[str, Any]: ...
```

当一个用它的人点开这个文件时，还是会猝不及防地撞上 `@workflow.defn`, `@workflow.signal` 这堆鬼画符。IR 只是在实体 Actor 的**调用方**面前藏起了 Temporal 的影子，却没能在**工作流定义的阅读者**面前遮住底裤。

L2 生成层应该直接甩出一个极度清爽的声明式 `EntityActor` 基类，然后靠着你的声明，去背地里把那个极其恶心的工作流类给糊出来：

```python
class BurstBucket(EntityActor[BurstBucketSpec]):
    """只声明形状；靠代码生成 + EntityActor 基类去生出那个带 @workflow.defn 的类。"""
    
    @signal_handler("event")
    async def on_event(self, payload: BurstEventPayload, state: BucketState) -> BucketState:
        if state.seed is None:
            state = state.with_seed(payload.l3_pick_key)
        return state.increment_count()
    
    @query_handler("seed_ticket")
    def get_seed(self, state: BucketState) -> str | None:
        return state.seed
    
    lifecycle = SleepThenClose(ttl_field="ttl")
```

这个基类会在背地里去糊那个带 `@workflow.defn` 的类、把信号/查询/运行方法全接好、像典狱长一样拿警棍逼着你去遵守确定性原则 (绝不准在 handler 里搞 I/O 操作)，然后自动生出极其丝滑的带类型查询描述符。用它的人这辈子都见不到 `@workflow.*` 这种脏东西。

这**不属于边界计划 IR 的范畴** —— 这是在它头顶上又盖了一层生成器和基类。这里只是把它当成未来的方向插个眼；等到 IR 彻底稳如死狗、并且我们至少踩过 2 个实体 Actor 落地场景 (第二个吃螃蟹的人才是检验 `EntityActor` 形状对不对的唯一真理) 之后，再来操刀设计它。

---

## 拿真刀真枪去验一验 (Validation experiment)

这是为了试探 "对着 IR 吐代码" 到底靠不靠谱而做出的第一次试水。

**第一次趟雷 (2026-05-04):** 小白鼠是 triage-rag L3 管道里的突发警报聚合器 (burst aggregator)。

- **吐出来的战利品：** 在内部打磨出来的，然后直接扔给了一个没有开源的下游服务去跑 —— 那是一个聚合器 activity 外加一整套测试 (大约 339 行代码 + 419 行测试)。虽然代码没开源，但它活生生逼出来的那一条血泪教训 (也就是那个要命的 `submit_side_effect` 缺口) 是可以去开源仓库里的 `bene/runtime/local.py` + `bene/temporal/runtime_impl.py` 查实锤的。
- **能不能过及格线：**
  - ✓ Activities (`should_advise`, `post_advisory`) 让完全不懂 Temporal 的老哥在 5 分钟内就看懂了
  - ⚠ 工作流类里还是特么漏着一堆 `@workflow.*` (这就逼着我们去搞了上面提到的那个 `EntityActor` 基类)
  - ✓ 在那两个 activity 里，比起活生生去敲裸装的 Temporal SDK，生生抠掉了 35 行代码
  - ✓ 测试用例死死咬住了那些最要命的冷启动竞态、重放安全、滑动时间窗边界、以及业务逻辑层面的幂等
  - ✓ 每个 activity 里极其规整地划分了两块业务逻辑区，而且都有路标 (marker) 死死守着
- **这波试水试出来最要命的破绽：** 最初设计的 IR 里虽然有 `business_idempotency_key` (业务幂等键) 和 `SideEffectLabel` (副作用标签) 这些高大上的概念，但**压根就没给那个最核心的 "检查-然后-写入" (check-then-write) 动作提供一个原子操作**。那个倒霉的业务方只能被逼得在现场用 `runtime.check_side_effect` 拼上 `runtime.record_side_effect` —— 这在 activity 遇到重试的时候，绝对是个 100% 会炸的 TOCTOU (Time-of-check to time-of-use) 竞态灾难。这也硬生生逼出了那个 `submit_side_effect` 原语，并且现在已经落地了 (`bene/runtime/local.py`, `bene/runtime/handle.py`, `bene/temporal/runtime_impl.py`)。如果不是硬着头皮去让生成器吐一次真实代码，这个巨坑绝对会被完好无损地端上生产环境去炸掉。
- **抽象层能逼死什么，又能容忍什么：** 业务方跑来吐槽，说把 `business_idempotency_key` 包装成一个*必须被点名道姓的概念*，硬生生逼着他们直面了那个极其哲学的拷问："在这个破场景里，到底什么才算是一个活生生的业务实体？" —— 这直接逼出了两套截然不同的骨架 (平时用 `(post_advisory, testrun_id, jira_ticket_key)`，大爆发时用 `(post_advisory, bucket_id, seed_ticket_key)`)。如果换做是一个直接徒手敲 Temporal `workflow_id` 的老哥，绝对两眼一摸黑就错过了这种细分。这就是这种 "极度克制的抽象" 最大的杀伤力：它不是让你少踩几个坑，而是让某一类愚蠢的 bug 在结构上连诞生的资格都没有。

下次的试水，必须去抓第二只实体 Actor 来当小白鼠 (比如请求去重器、或者是对话引擎 actor)，去看看这套 IR 是不是真的能在离开了警报聚合器这个温室之后，照样能极其稳健地泛化铺开。

---

## 别对它有什么不切实际的幻想

- **它不是跑来抢 Cursor 或者 Copilot 饭碗的自动补全框架。** 这里的代码生成只是 BENE 玩家关起门来自己用的一把特制兵器，绝不是什么包打天下的万金油。
- **它绝不是用来取代那套边界抽象原语的。** 它是以这些原语为靶子去射击的；不是来掀它们桌子的。
- **它从来没想过要把 Temporal 彻底挫骨扬灰。** 总有那么几个极其硬核的变态，就是喜欢光着膀子去生敲 Temporal。代码生成只是给 90% 的正常人铺设的一条选装捷径。
- **它绝不应该卡住任何现行业务的脖子。** 边界计划的那些基础原语必须先落地。代码生成是一层随时可以之后再盖上去的顶楼，可以在真实的业务需求上慢慢去磨。

---

## 顺藤摸瓜

- [核心哲学 (philosophy.md)](philosophy.md) — 扒一扒为什么 BENE 把身家性命全押在引擎 (harnesses) 的进化上
- [技能库 (skills.md)](skills.md) — 那些能抄的作业和套路到底藏在哪，以及怎么把它们掏出来
- [元引擎 (meta-harness.md)](meta-harness.md) — 看看 BENE 是怎么让引擎本身产生变异和进化的
- [用例地图 (use-cases.md)](use-cases.md) — BENE 现有的落地版图 (目前大头全在并行特种兵并发上；实体 Actor 才是代码生成这把刀真正要切进去的新蛋糕)
- `bene/runtime/handle.py` (运行时协议) + `bene/runtime/core.py` (边界 DTO) — 去看看 IR 的靶子到底长什么样
