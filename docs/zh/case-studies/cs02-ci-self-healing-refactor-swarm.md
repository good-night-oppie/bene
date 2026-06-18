# 把自愈 CI 当成多 agent 系统来做：设计、洞察与跨团队影响 (Self-Healing CI as a Multi-Agent System: Design, Insights, and Cross-Team Influence)

*Engineering · 2026-05*

---

## 背景 (Context)

大多数 CI 流水线都是一堆 bash 靠层层堆叠攒出来的。每加一项检查就是一个 job，每遇一次抖动（flake）就打一个补丁，每做一次重构就是一个没人认领的一次性 PR。时间一长，这条流水线事实上就成了团队的多 agent 系统——只不过它没有隔离、没有审计、也没有回滚。

本案例讲的是另一种做法：把 CI 当成一个显式的多 agent 系统，每个 job 都是一段带隔离、带审计轨迹、能做外科手术式回滚的 BENE agent 程序。它记录的是我们的架构取舍、跑起来之后才落定的几条洞察、如今我们推荐给其他团队的实践，以及这套模式如何重塑了相邻团队对流水线、重构和评审的认知。

它的目的不是甩给你一份配置——配置会过期——而是把那些真正吃重的设计决策，以及它们为什么重要，讲清楚。

## 问题拆解 (Problem Framing)

我们要重做的这条流水线，带着中型服务常见的三种坏味道：

- 一个 typecheck 的 advisory job，错误数每个迭代都在往上漂，却没有归属人。
- 一个测试套件，抖动重试把真实的可靠性 bug 藏在了绿勾后面。
- 一种评审文化：小重构要么大到没法安全上线，要么小到招不来评审人。

对这三件事来说，一个人手驱动的「一把清理」PR 都是错误的工作单元。我们想要的是 *N* 个小的、能独立评审、能独立回滚的单元——而且我们想让流水线自动把它们产出来。

## 设计 (Design)

整套架构由四个互相配合的组件构成，每一个都是同一个原语（primitive）的实例：一个隔离的 BENE agent（或一组 agent），只干一件事，并把它的发现写进一条 SQL 审计轨迹。

| 组件 | 关注点 | 产出 |
|---|---|---|
| 回归闸门 | 这次改动有没有把某个可量化的信号推过阈值？ | 带 delta 的通过/失败 |
| 自动修复 | 这处漂移是不是能轻松修掉？ | PR 分支上的一个 commit |
| 评审蜂群 | 有没有那种机器检测不出来的问题？ | 按角色拆分的评审笔记 |
| 重构蜂群 | advisory 错误能不能一个文件一个文件地往下削？ | 一捆按文件切分的补丁，外加一个审计 DB |

真正吃重的是下面这五个设计决策。

### 1. 一个 agent 管一个文件，而不是一个 agent 管一个任务

让单 agent 去「修掉所有类型错误」的尝试会撞上 context 上限，产出一坨摊得到处都是、根本没法评审的 diff。把活儿切成*一个文件一片*的分片（shard），我们才拿到了对的工作单元。每个分片的 diff 都小到两分钟能评审完，分片失败也只是局部的。

这跟 100-agent 规模教程里做迁移用的是同一套模式。那条约束——任何分片都不许碰超过一个文件——是吃重的，不是什么风格上的偏好。

> 同样的约束在 847 个分片上的样子，见 [tutorials/t08 — 100-Agent Scale](../tutorials/t08-hundred-agents-scale.md)。先读 t08，下面这些东西会显得理所当然，而不是凭空冒出来的。

### 2. 每个分片一个 `git worktree`，而不是每个分片一个 branch

并行的 branch 会产出并行的 branch 状态。一个补丁被否掉时，我们想干净利落地丢掉它，而不是在一个别的分片可能还依赖着的 checkout 上跑 `git reset`。给每个分片配一个 `git worktree`，就能拿到并行的文件系统状态，却不带并行的 branch 状态。清理就是把那个 worktree `rm -rf` 掉。

附带的好处：每个分片的 `mypy`/测试调用都跑在自己的工作目录里，于是验证之间没有跨分片的相互干扰。

> 「丢掉一个不惊动其余」这条性质，正是 [tutorials/t02 — End-to-End Self-Healing](../tutorials/t02-e2e-self-healing.md) 用 VFS checkpoint 演示的那一条。如果这里的回滚语义你不熟，读一下 t02；worktree 就是 t02 里逐 agent restore 在文件系统侧的对应物。

### 3. 用 hub 协调，而不是聊天

跨分片的学习是通过共享 VFS 里一个只读的 hub 目录发生的——agent 把笔记写进去（「这个代码库偏好 `Optional[X]` 而不是 `X | None`」），后面的分片一启动就能看到。这里没有 agent 之间的消息总线，没有共识协议，没有 token 爆炸。

它强制出来的纪律——「你学到了什么、下一个 agent 应该知道？」——本身就很有价值。我们现在在 PR 模板里也拿同样的问题去问人类评审者。

> hub 而非聊天为什么能在规模上成立：token 成本的算账见 [tutorials/t08 — 100-Agent Scale](../tutorials/t08-hundred-agents-scale.md)，隔离为什么能挡住 agent 之间的锚定偏差（anchoring bias）见 [tutorials/t03 — Security Swarm](../tutorials/t03-security-swarm.md)。两篇都短而具体；随便读哪一篇，都比从头自己把这套论证推一遍要快。

### 4. 先验证再保留

每个补丁在进产物包（artifact bundle）之前，都要在它自己的 worktree 里重新验证一遍。orchestrator 从不相信 agent 的自我陈述。具体说：一个补丁能被保留，当且仅当——把它打到一个干净的分片 worktree 上之后，验证指标（mypy 错误数、测试通过率等）严格变好。

重构蜂群的第一次试点跑出了八个补丁，其中三个被这一步丢掉了。这三个看起来都挺像那么回事，但没有一个真的削掉了错误。没有这一步，它们就上线了。

> [tutorials/t07 — Regression Guard](../tutorials/t07-regression-guard.md) 展示了同样的「对某个指标卡阈值」的思路，用在模型替换上。如果「先验证再保留」这道闸门对你来说还很新鲜，t07 有一个用 benchmark delta 跑出来的一页纸示例——读完那个，再回来。

### 5. 审计 DB 才是交付物

日志是给跑批过程中的人看的。审计 DB 是给跑完之后的下一个 agent（或人）看的。每一次 tool 调用、文件写入、状态变更、生命周期事件，都是一行 SQL。CI 的 artifact bundle 把这个 DB 也打进去，于是评审者可以直接查：

- 哪些分片用掉的 token 最多？
- 哪些分片的补丁被保留、哪些被丢弃，为什么？
- 每个分片往发现 hub（discoveries hub）里写了什么？
- agent 在哪里挂的，报的什么错？

正是这一处改动——把 DB 而不是日志当成交付物——让这套系统在规模上变得可评审。

> 这些查询模式，跟 [tutorials/t05 — Incident Response](../tutorials/t05-incident-response.md) 里用来做 12 秒根因分析的是同一套。schema 在 [Schema](../schema.md) 里有文档。如果你只想要那些现成的查询，直接跳到 t05。

## 供应链洞察 (Supply-Chain Insights)

有两个不那么显然的选择，我们现在认为对任何 agentic CI 都是必选项：

**runner 配置放在受代码所有权管控的路径下——但不要放在 `.github/workflows/` 下。** 一个搁在仓库根目录的配置文件，任何贡献者的 PR 都能改。把 runner 配置挪到一个受 CODEOWNERS 保护的路径下，改它就得有一次显式的 owner 评审。成本为零。它堵住的威胁——一个 PR 悄悄把模型路由改到另一个 provider 或另一个模型——是真实存在的。我们一开始把配置放在了 `.github/workflows/` 下；那是错的：GitHub Actions 会自动发现并*运行*那个目录里的每一个 yaml，把它当成一个 workflow。正确的归宿是一个同级目录，比如 `.github/bene/`——它照样能受 CODEOWNERS 保护，但不是 Actions 的 workflow 路径。**洞察：「受 CODEOWNERS 保护」和「会被自动执行」是两个互相独立的性质；把有特权的配置放在前者成立、后者不成立的地方。**

**给配置环境变量加一道运行时的路径守卫。** 每个蜂群脚本在启动时都会校验：在 CI 里跑时，配置路径必须解析到那个受保护目录之下。如果不是，脚本直接拒绝启动。这堵住了那个最显然的绕过手法：一个 PR 在别处加个配置文件，再把环境变量指过去。这道检查就两行代码。

这两个选择都是可测试的：一个挪走配置或拿掉守卫的 PR，会跟任何别的安全回归一样卡在评审上。

## 我们做对了什么 (What We Got Right)

- **刻意把流水线当成多 agent 系统来做。** 一旦把 CI 框定成「带隔离的 agent」，设计问题就有了清晰的答案：当然每个分片拿自己的 VFS；当然回滚是逐 agent 的；当然审计 DB 才是交付物。
- **把第一阶段做成 advisory。** 自动打补丁听着诱人，其实是错的。哪怕是八里中五的成功率，产出的噪声 diff 也足以把信号淹掉。advisory 产出能让评审者几分钟扫完那一捆东西。
- **拿评审蜂群对着 CI 脚本本身吃自家狗粮（dogfood）。** 评审蜂群产出的第一个不平凡的发现，就是关于它自己那个自动修复循环的。那一刻，向怀疑者证明了整套系统的价值。

## 我们做错了什么 (What We Got Wrong)

- **让 agent 互相读对方的 worktree。** 第一版允许只读挂载兄弟分片的 worktree。agent 立刻在跑批中途「借用」了一半的模式，把验证搞得抖来抖去。砍掉了；只共享 discoveries 就够了。
- **允许「顺手重排整个文件」的 diff。** 早期的 agent 会很热心地在一行修复旁边把整个文件重排一遍，把真正的改动淹没掉。我们现在用 prompt 把它框死：禁止碰目标错误行以外的任何东西，并且拒绝那些 diff 超出「每个错误一小笔行数预算」的补丁。
- **想给「显而易见」的修复跳过验证。** 根本没有显而易见的修复。验证这一步很便宜。永远跑它。

## 我们现在推荐的最佳实践 (Best Practices We Now Recommend)

1. 挑那个验证步骤能独立打分的最小工作单元。对类型检查来说是一个文件，对测试来说是一个失败的用例，对 benchmark 来说是一个回归的指标。
2. 让每个分片的工作单凭审计 DB 就能复现。如果评审者光靠 DB 答不出「这个分片干了什么」，那就是 orchestrator 在藏状态。
3. 让 orchestrator 保持无聊。杠杆来自那些约束（一个分片一个文件、先验证再保留、第一阶段 advisory）——而不是来自框架。
4. 把 runner 配置放到代码所有权后面，再加一道运行时守卫。把配置当成一个有特权的面来对待。
5. 把跨分片的学习沉淀进一个 hub 目录，而不是 agent 之间的聊天。
6. 评审审计 DB，而不是日志。攒一小套现成的 SQL 查询，覆盖成本、失败和发现；把它们写进 runbook 共享出去。

## 跨团队影响 (Cross-Team Influence)

这套设计以三种方式传播到了原始流水线之外：

- **一个相邻的数据团队**把同样的模式用到了他们的 schema 迁移流水线上。工作单元是一个分片管一张表，验证步骤是迁移自己的 dry-run plan，产物是一捆按表切分的 SQL 加上审计 DB。orchestrator 代码大约 150 行。
- **平台团队**把「runner 配置放在代码所有权之下」这条规则，定成了任何在 CI 里加载模型路由配置的工具的默认要求，而不只是 BENE。这现在是一条通用策略，不是 BENE 专属策略。
- **代码评审文化。** 评审蜂群按角色拆分的产出（「安全说 X；可靠性说 Y；测试说 Z」）改变了人类评审者组织自己 PR 评论的方式。无论蜂群有没有跑过，那个四角色拆分如今都成了不平凡评审的隐性模板。

## 与 Oppie 部署的对照 (Oppie Deployment Parallels)

重做过程中最有用的一次设计校验，来得有点出人意料：存储团队是怎么上线部署的？把两条流水线并排一比，同样的五个关注点落在了同样的五个位置上——两个团队之间没有任何协调。

| 关注点 | Oppie 部署 | BENE 自愈 CI |
|---|---|---|
| 晋升契约 | Spinnaker 流水线，阶段显式划分：`staging → pre-prod → prod`。每个阶段都有一个 Manual Judgement。 | 三道分支闸门：`feature → dev → main → tag`。`dev → main` 这一步是个夜间 bot，tag 这一步是人工 cherry-pick。两处都是显式的人工判断点。 |
| 配置作为有特权的面 | Helm values 和流水线 JSON 放在代码所有权之下；运行时守卫会拒绝来自受保护路径之外的配置。 | `.github/bene/` 是 `BENE_CONFIG` 唯一允许的前缀；CODEOWNERS 把守改动；runner 在启动时拒绝其他路径。 |
| 版本化、可复现的产物 | Released-Builds bucket：每次发布一份 SHA256 钉死的产物清单，不可变。 | `artifact_manifest.sh` 在 wheel/sdist 旁边产出一个扁平的 `<sha256>  <size>  <relpath>` 文本文件；`sbom.json`（CycloneDX）就挨着它放。 |
| 晋升前的 pre-prod 冒烟 | `pipeline_validation` job，对着 staging 集群跑关键路径操作。 | `scripts/ci/pipeline_validation/smoke.py` 校验关键 import 加上一次全新 DB 的 schema apply。同名，同职。 |
| 宣布成功前先泡一会儿 | Spinnaker 在晋升到 prod 之前会等过金丝雀告警窗口。 | `canary_watcher.sh` 在每个 `*-rc*` tag 上轮询 `release-blocker` issue 标签，持续 4 小时。 |
| 备份是一个层级，不是事后补丁 | 青铜/白银/黄金三层；备份落在另一个文件系统上，带保留策略和完整性校验。 | 青铜层（`/mnt/gravytrain/triage/bronze/bene-cicd/`）存放经 SQLite online backup API 产出的 DB 快照；带 sha256 加 JSONL 审计日志；restore 拒绝覆盖一个打开着的 DB。 |
| 漂移可见性 | 每周漂移报告，把已部署的配置和事实来源（source-of-truth）做对比。 | `drift_monitor.sh` 跑在周一的 cron 上，报告 pin 的新鲜度、mypy allowlist 的大小、覆盖率缺口、lockfile 的年龄。 |

这里的教训不是「Spinnaker 是 CI 的范本」。而是说，*晋升、不可变、冒烟、浸泡、快照、漂移*，是任何一条「必须跨越人和时间保持可信」的流水线吃重的原语。少了其中任何一个去搭流水线，这个卡点迟早会以一次故障、一次回归，或者一份谁都没法替自己辩护的纸面记录的形式冒出来。

这套流水线对照还逼出了几个我们自己本不会做的选择：

- **跳过用 BSD sysexits 语义。** 当一个 runner 够不着青铜层时（笔记本、GitHub 托管的 runner、临时容器），快照脚本以 `75`（`EX_TEMPFAIL`）退出。调用方把 `75` 当成「跳过，绝不算失败」。我们从部署运维「区分『这一步是故意跳过的』和『这一步坏了』」的实践里继承了这一点。没有这个区分，挂载缺失的失败看起来和损坏的失败一模一样，结果两者都被静音了。
- **一个哨兵 issue，编辑而不是追加。** 漂移报告每周重写同一条滚动评论，而不是新开一个 issue。Spinnaker 的看板也是这么干的——覆盖那个格子，别把历史分页堆出来。append-only 是事件的对的模型；滚动当前态（rolling-current）是状态的对的模型。
- **分支保护卡在 job 名上，不卡在 workflow 名上。** 改个 workflow 名，不该悄无声息地把一项必需检查禁掉。这是从部署侧学来的：流水线 ID 才是契约，产出它的那个文件路径不是。

## 待解问题 (Open Questions)

- **自动打补丁的判据。** 第一阶段是 advisory。第二阶段应该自动打那些过了硬标准的补丁（单文件 diff、验证指标变好、无格式噪声、评审者打过标签）。难点在于怎么定义「无噪声」而不过拟合。
- **跨分片重构。** 有些重构确实需要把多个文件一起改。当前系统会拒掉它们。未来的一个变体应该在前头就识别出这类情况，把它们路由到另一种 agent 形态（一个分片，多个文件，更严格的人工评审）。
- **成本上限。** 逐分片的 token 预算管用。逐 PR 的 token 预算还停留在临时拍脑袋。审计 DB 让这件事变得可量化；我们还没接上一个硬性上限。

## 另请参阅 (See Also)

如果你对这些模式还不熟，按这个顺序读；每一篇都把本案例里一段多自然段的解释，收拢成一个具体、自洽的走查。

- [tutorials/t10 — Self-Healing CI Overnight](../tutorials/t10-ci-overnight-bene-swarm.md) ——*怎么做*。可跑的脚本、排障表、审计 DB 查询。当你想把系统上线、而不是理解它时，用这篇。
- [tutorials/t08 — 100-Agent Scale](../tutorials/t08-hundred-agents-scale.md) ——*一个 agent 一个文件*的模式，在 847 个分片上的样子。一遍读下来就把「分片大小就是评审单元」这条洞察内化掉。
- [tutorials/t02 — End-to-End Self-Healing](../tutorials/t02-e2e-self-healing.md) ——*外科手术式回滚*的心智模型。看完这篇，逐分片 worktree 清理就不用再多解释了。
- [tutorials/t03 — Security Swarm](../tutorials/t03-security-swarm.md) ——*并行评审者 + 隔离*的模式，带锚定偏差的量化测量。最快理解评审蜂群角色拆分的途径。
- [tutorials/t07 — Regression Guard](../tutorials/t07-regression-guard.md) ——*对某个指标卡阈值*的闸门，用在模型替换上。「先验证再保留」最便宜的一个例子。
- [tutorials/t05 — Incident Response](../tutorials/t05-incident-response.md) ——12 秒内搞定的*审计 DB SQL*。本案例里那些现成查询，放在上下文里的样子。
- [Checkpoints](../checkpoints.md) 和 [Schema](../schema.md) ——当你要的是原语参考，而不是又一个场景时。
- [Use Cases — Self-Healing CI](../use-cases.md#self-healing-ci-regression-gate-auto-fix-review-and-refactor-swarms) ——一页纸的小结，链接回这里。
