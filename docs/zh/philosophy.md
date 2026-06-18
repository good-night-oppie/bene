# BENE 设计哲学

## BENE 究竟是什么

**BENE** = **B**reeding-program · **E**volutionary · **N**exus · **E**ngrams —— 一套贝尼·杰瑟里特 (Bene Gesserit) 式的 harness。

- **B**reeding-program (繁育计划) —— 演化层面的 Meta-Harness 搜寻：一种极度耐心的、跨越多代的筛选机制，向着更完美的 harness 进化，一如姐妹会跨越千年繁育出魁萨茨·哈德拉赫 (Kwisatz Haderach)。
- **E**volutionary (演化) —— 那些能在跨代传递中产生复利效应的 harness 策略，赢家必须存续，而不是每次都在冰冷的零起点重新摸索。
- **N**exus (连结核心) —— 那个将所有 agent 牵绊在一起的、完全可审计的 SQLite 数据库。一个 nexus，唯一的真相源 (source of truth)。
- **E**ngrams (记忆印记) —— 那些随时可检索的执行轨迹 (**traces**)：它们构成了基于 trace 进行 RAG 的语料库，也就是 BENE 版本的圣母 "Other Memory" (先祖记忆)。下一个登场的 agent 永远不用从零开始，它天生继承先祖的记录。

这是我们在 Oppie 用来支撑大规模 agent 执行真实 triage (分诊)、on-call 和 SDLC 工作负载的底层编排基座。每个 agent 会分配到一个背靠 SQLite 并且完全物理隔离的虚拟文件系统 (VFS)、一条只能追加写入 (append-only) 的事件日志，以及一条支持任意回溯的 checkpoint 时间线。包裹着这套内核的，是一个负责**演化**的 Meta-Harness，它能不断优化 agent 履行职责的执行策略。

BENE 不是一个大模型。它也绝不是某种企图用所谓 "优雅的抽象" 去抹平各家 LLM API 差异的平庸框架。BENE 是 harness 层，它的职责只有一项：把充满不确定性与非确定性的 LLM 调用，死死钉成可审计、可横向对比、可严格复现的生产级别操作。

---

## 我们为什么需要一个 Harness？

> 兽物的意识无法超越眼前所见，更不会意识到其猎物或将灭绝……它们，只会毁灭，不会创造……兽类的快感局于感官，止于认知……而人，则需框架逻辑，来理解世界……主动选择专注的意识，来搭建思维的框架……体内细胞和神经最深处的意识，驱动着行为……万物，无永恒，忠于意识，生于本能。

野兽的认知边界永远超不出它的视线所及。它只凭本能对猎物、威胁或者眼前的刺激做出应激反应 —— 它只会毁灭，不会创造。人类之所以为人，是因为人类需要用**框架与逻辑**来理解世界：这种经过刻意选择与高度聚焦的意识，在付诸行动之前就已经搭好了思考的脚手架。

脱去这层框架，一个光秃秃的 LLM 就是那头野兽。它极度擅长对当前 context window 里塞满的东西做出即时反馈。一旦任由它在没有约束的环境里撒野，它会带着无比自信的态度一路反应下去，直到毁掉整个工作树 (working tree)，逼迫你执行全局恢复，或者理直气壮地给出一个彻底错误的答案。它没有 Other Memory，没有 nexus，更缺乏一种能审视自身轨迹的内在视野。

BENE 正是那套让 agent 学会**创造**而不是仅仅**反应**的框架逻辑。组成名字的这四个字母不是为了凑字数的营销辞藻 —— 它们是四条被铸入底层架构的铁律。**B**reeding-program 和 **E**volutionary 循环，保证了随着时间推移变强的是 harness 本身，而不必苦等模型厂的恩赐。**N**exus 则是那颗唯一的数据库心脏，它让每一次动作都乖乖躺在可审计、可控制的边界里。**E**ngrams（那些留痕的 traces），则是将前代走过的每一步转化为后辈基石的记忆体。这一切加起来，就是一头只会做出应激反应的 LLM 野兽，和一个真正懂得创造的 agent 之间的分水岭。

---

## 两大核心信念

### 1. 面对 Triage 场景，基于 Trace 的 RAG 碾压基于 Prompt 的 RAG

对于一个负责分诊 (triage) 的 agent 来说，最昂贵的检索目标根本不是 "系统文档" 或者 "代码库"。最昂贵的情报是：**上一个 agent 在这遇到问题时到底尝试了什么，以及随之引发了什么后果**。BENE 直接把执行轨迹 (trace) 本身变成了第一公民级的语料库：

- 每一次 tool call、每一个输出结果、每一次状态变迁，统统落入 event journal。
- 每一个具有业务价值的产出物，都会被内容寻址机制打入 blob store。
- 每一次决策逻辑，都必须能够通过 SQL 查询、FTS5 全文检索以及 agent 级别的隔离读取直接抽调出来。

下一位接手的 agent 绝非白手起家。它会在属于自己的 VFS 里打开一份现成的文件，里面已经齐齐整整地记录着此前的 triage 历史、失败模式归类、前人失败的修复尝试，以及所有的回滚标记。**以执行轨迹作为第一检索源 (Retrieval over execution traces)**，这正是拉开代差的核心壁垒。

### 2. 该演化的是 Harness，绝不该是模型

面对一种全新形态的 triage 挑战，我们绝不会跑去微调 LLM。我们选择演化包裹在模型外面的这层 harness：prompt 模板、tool 的组合顺序、检索策略以及判定修复是否生效的 verifier。Meta-Harness 只是一个非常轻量级的演化循环：它不断提出新的 harness 变体，丢进基准测试里跑，然后把胜出者留存在帕累托前沿 (Pareto frontier) 上。

这种做法极其廉价（不吃 GPU 算力）、极其可逆（每一个 harness 只不过是一份带着哈希值的代码 blob）、极其透明（每一次演化迭代全在 event journal 里记着账），并且具有可怕的复利效应（胜出的套路会固化进项目的 skill library 中，直接成为下一次演化搜索的种子）。

---

## 拼图从何而来

BENE 纯粹由那些已经被证明管用的方案组装而成。我们不发明轮子，我们只负责整合它们，并让它们在同一套逻辑下咬合运转：

| 核心能力 | 来源 | 帮 Oppie 解决了什么问题 | BENE 文档指引 |
|---|---|---|---|
| 跨 Agent 共享 FTS5 Memory | claude-mem (Alex Newman) | Triage agent 在跨 session 甚至跨任务时总是犯同样的低级错误 | [memory.md](memory.md) |
| 跨 Agent 共享 Skill 库 | Zhou et al. 2026 (arXiv:2604.08224) | Agent 反复重新推演一模一样的监控看板查询、去重启发式算法和回滚手册 | [skills.md](skills.md) |
| Shared log + 投票协同 | LogAct (arXiv:2604.07988) | 像抹杀 agent、执行大范围 checkpoint 恢复这类高危操作，必须有共识机制和审计轨迹背书 | [shared-log.md](shared-log.md) |
| 高紧凑上下文符记化 (AAAK) | MemPalace | 冗长且不断膨胀的 context 吃光了准确率，还烧光了搜寻任务的 token 预算 | [meta-harness.md](meta-harness.md) |
| 停滞破解 + 共同演化 | CORAL (arXiv:2604.01658) | Proposer 在某一种特定的 harness 构型上死磕并陷入局部最优 | [meta-harness.md#coral-getting-unstuck-v020](meta-harness.md#coral-getting-unstuck-v020) |
| 失败根因诊断 (Verifier) | EvoSkills (arXiv:2604.01687) | 大面积的不透明失败让下一轮迭代就像无头苍蝇一样拿不到 actionable 的反馈 | [meta-harness.md](meta-harness.md) |
| 自动化参数调优 | Meta-Harness (arXiv:2603.28052) | 纯手工硬写的 prompt engineering 根本无法在发版之间产生跨代复利 | [meta-harness.md](meta-harness.md) 和 [tutorials/t01](tutorials/t01-bene-meta-harness.md) |

VFS 引擎、checkpoint 时间线、event journal 日志流以及层级隔离机制，这些才是 Oppie 团队真正的原创心血。它们构成了让上面这张表格里所有能力在同一个进程、同一个数据库里完美拼合的底层基座。

---

## 运作铁律

### 信任来自审计日志，绝不来自模型拍胸脯的自信

一个说 "bug 在模块 X 里" 的 triage agent，跟另一个说 "bug 在模块 X 里，**并且这里有一条 SQL 查询证明，在 14:32 到 14:51 之间它成功捕获了 847 条 `ConnectionPoolError` 报错事件**" 的 triage agent，根本不是一个物种。BENE 的所有机制设计，都是在强迫系统极容易地生成第二种论述。Event journal 是绝对可被 SQL 查询的。Token 开销、tool calls 调用流以及耗时，在这里全是一等公民的数据列。

### 隔离机制没有任何讨价还价的余地

每个 agent 都必须老老实实在自己的 VFS 里干活。两个同时并行审计同一个 PR 的 triage agent 绝不允许互相踩踏对方的工作区。哪怕修出了问题，也能在 0.3 秒内通过 checkpoint 干净利落地回滚，绝不会惊扰项目里的其他 agent。只有把隔离做到这个份上，你才敢把一个拥有自主执行权的 agent 散养在高度逼近生产环境的链路里，而不用在事后苦着脸去写一份关于*编排层怎么崩了*的 postmortem。

### 核心目的就是吃复利

当值班工程师第一次用 BENE 冲进一个 `iss_storage_unreachable` 事件的案发现场时，他们是在做纯粹的调查。但等到第二次，BENE 早就备好了一套沉淀下来的 skill、一条先前的执行 trace，以及上周 verifier 开具的诊断报告。等到第五次爆雷时，harness 早就经历过迭代演化，接手的 agent 只需要跑两个 tool call 就能直接揪出罪魁祸首。这一切当然不是魔法自动变出来的 —— 这是当你拥有一套把 "存一次，到处用" 做到极致廉价的基座，并辅以一个只奖励胜出者的 Meta-Harness 后，必然产生的结果。

### 无法复现的东西，坚决扔掉

BENE 随版发布的每一次更新，都会连带打包它正在使用的 harness、评估它的 benchmark 靶场、繁育出它的初代执行种源，以及能丝毫不差还原出任意一条决策依据的完整 event journal。如果你无法重播还原当时的现场，那这事就当没发生过。

---

## 我们绝对不碰什么

- **我们绝不重复发明已经被解决的问题。** 只要有现成的论文或者开源组件已经把活儿干得足够漂亮，我们就直接集成并且署名致敬。
- **我们绝不添加那些没有实操 operator 兜底的需求。** BENE 里的任何一个能力，都能追根溯源到某个因它获益的真实 triage、on-call 或者 SDLC 负载场景上。
- **我们绝不藏匿技术出处。** 代码里、文档里、changelog 里都会挂着集成方案的溯源 citation。去看原版论文。
- **我们绝不构建自己都无法维护的过度抽象。** 任何胆敢破坏整体拼合能力 (composability) 的花哨功能，都不值得被发版。

---

## 悬赏区

我们正在持续搜集以下领域的先期研究 (prior art)：

- 粒度能够精细到子 agent (sub-agent) 级别，而不是动辄覆盖整个 VFS 的精准回滚机制。
- 远比目前只有同意/否决二元投票要丰富得多的跨 agent 信任建模方案。
- 能够根据任务危急程度动态调整上下文预算的自适应机制 (比如关键告警的翻页与普通文档的翻页采取完全不对称的策略)。
- 生命周期决策策略 —— 到底什么时候该强制让一个 agent 退休？什么时候该克隆并发？什么时候该提拔一个独苗 (singleton)？

如果你读过切中要害的硬核文献，请直接丢进我们的 issue tracker。整合标准完全遵循上文的原则。你的贡献会被铭刻在这里。

---

## 贡献指南

BENE 是为了 Oppie 内部的 AI Triage 战役以及更深远的愿景而生的。最有杀伤力的贡献途径如下：

1. 一项你深入研读过且急需落地整合的论文研究。
2. 一份直接拔自真实生产运维现场且附带可复现用例的 bug 报告。
3. 一份 benchmark 压测结果 —— 无所谓这套能力在真实的 triage 或 SDLC 任务里到底是起飞了还是拉垮了，数据说话。

对于 Oppie 内部的贡献者，待发力的积压需求池已经全数躺在 `bene` 仓库的 epic tracker 以及 engineering-services 的 Jira 队列里。
