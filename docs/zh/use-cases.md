# BENE 常见使用场景 (Use Cases)

这是一份速查兵器谱。每条都是一眼就能看懂的缩影 —— 痛点在哪，BENE 能给你什么火炮，以及想深挖该去哪看文档。

> **这份兵器谱该怎么用：** 扫一眼大标题，看中哪个跟你现在的痛点对上了，就顺着传送门点进去。手把手的实战教程都在 `tutorial` 里；至于为什么要这么设计的哲学探讨，都在 `case study` 里。

---

## 狼群代码审查 (Code Review Swarm)

**痛点 (Problem).** 传统的串行 Code Review 让审查者的脑子在安全、性能、代码风格和测试覆盖率之间疯狂横跳。锚定偏见 (Anchoring bias) 和大脑疲劳会让极其明显的漏洞被直接放过去。

**BENE 方案.** 直接放出四头互不干扰的狼 (平行审查者)，每头狼锁死在自己的专属虚拟文件系统 (VFS) 里 —— 狼跟狼之间绝对看不见对方的答案。最后靠一条 SQL 把所有狼咬出来的洞汇总。

→ 实战演练: [t03 — 安全审查狼群 (Security Swarm)](tutorials/t03-security-swarm.md) · 代码样板: `examples/code_review_swarm.py`

---

## 并行大重构：敲代码 + 写测试 + 补文档同步推进

**痛点 (Problem).** 敲代码、写测试和补文档这三件事明明是可以各干各的，但在现实中却总是被悲催地排成串行。

**BENE 方案.** 直接拉起三个并行的 Agent，每个都关在自己的 VFS 结界里，给它们喂同一套源码当饲料，让它们同时开工。

→ 代码样板: `examples/parallel_refactor.py` · 终端指令: `bene parallel -t impl … -t tests … -t docs …`

---

## 炸机自愈 (Self-Healing Agent)

**痛点 (Problem).** 某步极其危险的操作把系统搞炸了，结果在回滚擦屁股的时候，连带把旁边好好干活的模块也一起炸飞了。

**BENE 方案.** 在趟雷之前先拍个快照存档。炸机后，几毫秒内就能对单个 Agent 实施外科手术式的时间倒流，旁边的 Agent 连根毛都不会掉。

→ 实战演练: [t02 — 全链路自愈闭环 (End-to-End Self-Healing)](tutorials/t02-e2e-self-healing.md) · 进阶心法: [快照与时空回溯 (Checkpoints)](checkpoints.md)

---

## 案发现场验尸 (Post-Mortem Debugging)

**痛点 (Problem).** Agent 把什么东西搞砸了。系统日志只能告你它砸了什么，却没人能按时间线说清楚它 *为什么* 要去砸。

**BENE 方案.** 它拔过的每一把刀、写过的每一行字、脑子里的每一次状态突变，全被死死钉在了 SQL 的行记录里。你只需要敲一行查询，就能把整个案发过程按秒级还原出来。

→ 数据底座: [数据库骨架 (Schema)](schema.md) · 终端指令: `bene logs <agent-id>`, `bene diff`, `bene search`

---

## 凌晨两点夺命 Call (Incident Response)

**痛点 (Problem).** 生产环境炸了。老板要你按分钟计给出死因，不是按小时。

**BENE 方案.** 直接去事件流水账里扫射报错模式和最近刚改过的文件；几秒钟内把真凶揪出来。

→ 实战演练: [t05 — 应急响应 (Incident Response)](tutorials/t05-incident-response.md)

---

## 数据库数据迁移紧急刹车 (Migration Rollback)

**痛点 (Problem).** 一个 200 万行的背填 (backfill) 脚本跑到第 84 万 7 千行时，毫无防备地一头撞死在了一堆 NULL 上。

**BENE 方案.** 只对那个搞迁移的 Agent 进行外科手术式的状态回退。旁边那些正在这堆没被污染的数据上跑分析的 Agent 继续狂奔，根本不需要叫停。

→ 实战演练: [t04 — 数据迁移回滚 (Migration Rollback)](tutorials/t04-migration-rollback.md)

---

## 骨灰级安全审计 (Security Audit Swarm)

**痛点 (Problem).** SQL 注入、密钥泄露、越权访问、反序列化炸弹 —— 四个极其硬核但完全不搭界的威胁模型，全都压在一个早就累成狗的安全审核员头上。

**BENE 方案.** 给每个攻击面单独配一条疯狗 (Agent)，绝对的结界隔离，最后靠 SQL 把四张嘴撕出来的洞无缝拼起来。

→ 实战演练: [t03 — 安全审查狼群 (Security Swarm)](tutorials/t03-security-swarm.md)

---

## 无人值守的研究实验室 (Autonomous Research Lab)

**痛点 (Problem).** 带着 N 个假想去做实验，跑在一台破机器上，最后得出一张满屏数字的 TSV 表格 —— 至于这些数字到底是怎么跑出来的，早就成了一笔死无对证的烂账 (loses provenance)。

**BENE 方案.** 让 N 个验证假想的 Agent 并排着跑；跑完之后，所有的实验中间过程全能通过 SQL 跨越不同的跑次进行交叉比对。

→ 实战演练: [t06 — 机器学习炼丹炉 (ML Research Lab)](tutorials/t06-ml-research-lab.md)

---

## 全链路 CI 自愈流水线 (End-to-End Self-Healing CI，实战篇)

**痛点 (Problem).** 一行脑残的修复代码引发了雪崩式的四个连环挂。在整个代码库层面搞硬重置，直接把其他正在干活的 Agent 全埋了。

**BENE 方案.** 靠单兵快照 (Per-agent checkpoint) 兜底、外科手术式的时间回溯、从不可磨灭的印记流水账里扒出死因、生成对症下药的代码，最后全线飘绿。

→ 实战演练: [t02 — 全链路自愈闭环 (End-to-End Self-Healing)](tutorials/t02-e2e-self-healing.md)

---

## 机器学习研究：在一局里同时验证正交假想

**痛点 (Problem).** 架构、优化器、批次大小 (batch)、正则化 —— 四个完全独立、互不干扰的调参旋钮。

**BENE 方案.** 放出四条狗同时去跑四条岔路；谁赢了就把谁存档定格；连实验报告都会自己写出来。

→ 实战演练: [t06 — 机器学习炼丹炉 (ML Research Lab)](tutorials/t06-ml-research-lab.md)

---

## 严防模型智商衰退 (Model Regression Guard)

**痛点 (Problem).** 偷偷换了个新模型，结果在某个极其致命的基准测试 (benchmark) 上，智商悄无声息地倒退了。

**BENE 方案.** 在 CI 里架起一道击杀闸门 (gate)，只要跌破红线当场拦截部署，并且直接唤醒 元引擎 (Meta-Harness) 开始自我抢救。

→ 实战演练: [t07 — 智商防倒退闸门 (Regression Guard)](tutorials/t07-regression-guard.md) · 底层黑科技: [元引擎进化 (Meta-Harness)](meta-harness.md)

---

## 抓内鬼 (欺诈检测)：拿元引擎去打样本极度不平衡的烂仗

**痛点 (Problem).** 阳性样本少得可怜 (Rare positive class)；漏放一个坏人的代价大到无法承受；人工捏造特征 (feature engineering) 的脑洞已经枯竭了。

**BENE 方案.** 让元引擎的 提案生成器 (Proposer) 去啃之前翻车留下的印记，硬生生从死尸堆里学会怎么列出一份抓内鬼的红旗警告清单。

→ 底层黑科技: [元引擎 — 血泪实录 (Meta-Harness — Examples)](meta-harness.md#sources-and-worked-examples) · 祖传代码: `examples/meta_harness_fraud_detection.py` (注意：`fraud_detection` 这玩意没被硬编码进 `-b` 选项里；`-b` 只认 `text_classify` / `math_rag` / `agentic_coding`)

---

## 多路特种兵协同进化 (CORAL 框架)

**痛点 (Problem).** 负责探路的单兵 Agent 撞墙了，脑子彻底卡死了 (plateaus)。

**BENE 方案.** 让 N 个特种兵共享一条帕累托前沿 (Pareto frontier)；一旦发现有人卡死停滞不前，立刻强行触发跨品种的基因杂交 (cross-pollination)。

→ 底层黑科技: [元引擎 — CORAL 破局策略 (Meta-Harness — CORAL)](meta-harness.md#coral-getting-unstuck-v020)

---

## 人海战术：847 个特种兵，8 分钟，0 翻车

**痛点 (Problem).** 一场牵扯到 847 个文件的 Python 2 往 Python 3 的大迁徙。排队串行改简直就是做梦；而如果在这种规模下共享状态，系统绝对会当场崩溃。

**BENE 方案.** 一文件一特种兵，靠中央枢纽 (hub) 居中调度，每个特种兵都能独立回滚，最后把那个记录了所有案底的数据库作为交付物上交。

→ 实战演练: [t08 — 百鬼夜行级并发 (100-Agent Scale)](tutorials/t08-hundred-agents-scale.md)

---

## 能自我抢救的 CI：防跌闸门、自动修虫、代码查杀与重构群狼

**痛点 (Problem).** 类型检查的警告日积月累越攒越多；靠着无脑重试把不稳定的玄学 bug 全掩盖过去了；那种不痛不痒的小重构压根没人愿意花时间去看。

**BENE 方案.** 用 BENE 写四个相互打配合的 CI 作业：防跌闸门 (regression gate)、自动修虫 (auto-fix)、代码查杀群狼 (review swarm) 和重构群狼 (refactor swarm)。每个作业都在自己切出来的 git worktree 里搞事，死守 "不验证不准合并 (verify-before-keep)" 铁律，最后把案底数据库当成唯一的交付物。

→ 实战演练: [t10 — 能在熬夜时自动修虫的 CI 狼群 (Self-Healing CI Overnight)](tutorials/t10-ci-overnight-bene-swarm.md) — *怎么落地* (脚本怎么敲、流水线怎么接、炸机了怎么排雷)
→ 深度剖析: [cs02 — 拥有自愈能力的 CI (Self-Healing CI)](case-studies/cs02-ci-self-healing-refactor-swarm.md) — *为什么要这么干* (设计哲学、心路历程、以及怎么靠这套东西去怼赢其他团队)

---

## 连锅端走与共享案底 (Export & Share)

**痛点 (Problem).** 想把一个 Agent 在案发现场的所有活体状态连根拔起，甩给队友看。

**BENE 方案.** 它的全部家当 —— 挂载的文件、拔过的刀、脑子里的状态、流水账、所有存档的快照 —— 全被死死封印在那一个 `.db` 文件里。复制它、用任何一个破 SQLite 客户端打开它、把它通过微信发给队友。

```bash
bene export <agent-id> -o agent-snapshot.db
bene import agent-snapshot.db
cp bene.db full-backup-$(date +%Y%m%d).db
```

→ 数据底座: [数据库骨架 (Schema)](schema.md)

---

## 宣判词黑话大全 (Verdict Glossary)

那套自愈 CI 脚本在往 PR 评论区或者案底工件 (artifacts) 里吐口水时，只会用极其可怜的一丁点词汇。这些暗号在各个阶段都是绝对锁死的，最好背下来。

| 宣判词 | 谁会吐出这个词 | 什么意思 | 看到这个词后该怎么做 (Caller policy) |
|---|---|---|---|
| `pass` | 防跌闸门 (regression-gate), 分诊员 (classifier) | 量出来的指标全在红线以上；junit 跑完没报一个错 | 放行，继续往下跑 |
| `fail` | 防跌闸门, 分诊员 | 指标跌破红线了，或者 junit 报了错 | 死锁合并按钮，不准合 |
| `flaky` | 分诊员 | 挂掉的姿势跟案底库里的某种 "玄学挂法 (flake)" 撞脸了，而且重跑一次居然又绿了 | 打个警告标签 (advisory)；别去卡合并 |
| `base-not-green` | 分诊员, 防跌闸门 | 这个 PR 从主分支分叉出来的那个起点 (parent commit) 本来就是带病的 | 默认发个退出码 5 (也就是贴个 ::warning 标签)；要是强开了 `BENE_STRICT_BASE=1` 就直接发退出码 4 当场击毙 |
| `cov-drop` | 分诊员 | 实测的代码覆盖率比 `.coverage-floor` 定下的底线还要低，而且跌幅超过了 `BENE_COV_DROP_LIMIT` (默认容忍 0.1%) | 死锁合并按钮，不准合 |
| `ratchet: noop` | 强推主线 (push-main), 覆盖率棘轮 (ratchet_coverage) | 底线没动；覆盖率没能冲破 `底线 + 1%` 的门槛 | 放行，啥都不提交 |
| `ratchet: 42 -> 47` | 强推主线, 覆盖率棘轮 | 底线被强行抬高了 (一个 PR 最多抬 5 分，封顶 98 分) | 偷偷往主线打个 `[skip ci]` 的提交，把底线写死 |
| `canary: clean` | 标记发布 (release-tag), 灰度哨兵 (canary_watcher) | 丢在灰度池里泡了 4 个小时，没收到任何带 `release-blocker` 标签且点名了这个版本的客诉 | 盖章：可以全量发布 |
| `canary: blocker` | 标记发布, 灰度哨兵 | 发现了一个没关单、带 `release-blocker` 标签、而且指名道姓骂了这个版本的 issue | 锁死发布流程；立刻把修复代码 cherry-pick 捞回来 |
| `EX_TEMPFAIL` (75) | 数据库快照/回溯, 灰度哨兵 | 某种极其弱智的外部原因导致这活干不下去 (比如 NFS 没挂载上，缺了 gh 命令行工具，环境变量没设) | 悄悄跳过；**绝对不准在防线没搭好的时候装作没事放行 (never fail-open)** |
| `drift: warn` | 偏移监控 (drift_monitor) | 某个指标越过了 "警告线" (比如版本落后 > 50 个，覆盖率缺口 > 30%，锁文件老于 30 天) | 把这破事挂在 Step Summary 上恶心人；但不准卡合并 |

这两条铁律造就了上面这份黑话表：

1. **宣判词才是最终契约；流水日志连狗都不看。** 如果一个 PR 评论居然要人 "详情请看流水线日志"，那简直就是耻辱。上面这些词全是枚举值里的死锁项，会被直接写进案底工件旁的 `triage.json` 里。下游的自动化工具只吃这些死板的枚举词，它们才不看你写的文言文。
2. **`EX_TEMPFAIL` 压根就不是代码的锅。** 连不上跑青铜模型的机器、读不到输入的配置文件、系统里没装这个 CLI —— 这些全是环境抽风，跟流水线代码没一毛钱关系。这个极其特殊的退出码，就是为了把这种破事跟真正的炸机区分开，好让调它的人决定：是该悄悄跳过、去钉钉骂人、还是直接强行拔电源 (hard-fail)。

→ 实战演练: [t10 — 能在熬夜时自动修虫的 CI 狼群 (Self-Healing CI Overnight)](tutorials/t10-ci-overnight-bene-swarm.md) 会教你这些宣判词最后到底会从流水线的哪个口子里吐出来。 → 深度剖析: [cs02 — 拥有自愈能力的 CI (Self-Healing CI)](case-studies/cs02-ci-self-healing-refactor-swarm.md#oppie-deployment-parallels) 扒出了 `EX_TEMPFAIL` 这个黑科技是怎么从运维部署的死人堆里爬出来的。

---

## 对症下药导航表

| 如果你快被这事逼疯了… | 就从这里杀进去 |
|---|---|
| 想搞一堆被死死隔离的并行审查狗 | [t03 — 安全审查狼群 (Security Swarm)](tutorials/t03-security-swarm.md) |
| 想要那种连一根毛都不掉的外科手术式回滚 | [t02 — 全链路自愈闭环 (End-to-End Self-Healing)](tutorials/t02-e2e-self-healing.md) |
| 想拿某个死板的指标当拦截部署的红线 | [t07 — 智商防倒退闸门 (Regression Guard)](tutorials/t07-regression-guard.md) |
| 在极其变态的规模下，想搞一文件一特种兵 | [t08 — 百鬼夜行级并发 (100-Agent Scale)](tutorials/t08-hundred-agents-scale.md) |
| 怎么拿 SQL 从案底数据库里挖坟 | [t05 — 应急响应 (Incident Response)](tutorials/t05-incident-response.md) |
| 怎么把 CI 彻底改造成一个多 Agent 的蛊林 | [t10](tutorials/t10-ci-overnight-bene-swarm.md) + [cs02](case-studies/cs02-ci-self-healing-refactor-swarm.md) |
| 怎么让它自己去死海里搜出正确的提示词 | [元引擎进化 (Meta-Harness)](meta-harness.md) |
| 扒一扒骨架和那些最原始的积木块 | [数据库骨架 (Schema)](schema.md) · [时空回溯 (Checkpoints)](checkpoints.md) · [深层架构 (Architecture)](architecture.md) |
