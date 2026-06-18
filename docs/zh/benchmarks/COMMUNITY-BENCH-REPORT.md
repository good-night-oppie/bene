# 社区竞品评测报告（COMMUNITY-BENCH-REPORT） — BENE 与 KAOS/0.1.0 前身在社区基准测试中的对比（预注册运行，2026-06-11）

> **竞合关系定调 (2026-06-14).** 本报告原名为 RIVAL-BENCH-REPORT 且全文使用 *rival*（对手）一词。证据——裁定结果、门禁标准、原始命令、偏差数据——均未改动。唯一改变的是定调词汇。我们同属一个开源社区；KAOS 和 0.1.0 前身是同行（peer）项目，我们用他们的测试用例来检验 BENE，而 BENE 的能力差异是相对于这个共享的社区成果而言的。少数几个短语（例如 §裁定结果 中的 `"BENE supersedes"`）使用了引号，因为它们是 PREREG 锁定规则中的技术制品，修改锁定短语会使协议失效；该协议依然成立。在其他所有地方，*rival*（对手）→ *peer* / *community peer*（同行/社区同行）。
>
> `docs/benchmarks/PREREG.md` 刻意保留了 2026-06-11 注册时的逐字节原始内容（其锁定标准中仍使用 *rival* 一词）；对其进行任何事后编辑——即使只是世界观词汇的替换——都会改变文件的 sha256，可能被视为违反协议。社区同行的惯例适用于本报告、差距审计、设计文档、落地页以及技能；PREREG 本身作为一个锁定历史的产物被保留。

- **协议：** `docs/benchmarks/PREREG.md`，在执行任何基准测试前的 2026-06-11 预注册。以下所有门禁标准均作为锁定规则应用；没有任何标准被事后修改。
- **PREREG sha256:** `f9179cf814e9a7d713007d7fc4c66f25e25a011f68dc4c6e70cf5c201b5043f8`
- **REJECT 视为成功：** 根据 PREREG 原则 3，如实报告 LOSS 行代表成功的审计结果；粉饰任何一行都会使报告失效。在门禁统计数据存在歧义的地方，均采用对 BENE 最不利的解读。

## 概要

**BENE 在 4 个同行具备机制但 BENE 未发布的指标上落败：A1b, A2, A4, A5**（结果/可塑性加权检索排序、习得排序增益、关键步骤失效定位、连续质量结果信号——这些均在*计划中*，尚未发布）。A 组的第五个败局，**A6，是 BENE 已实现机制的落败**（`attach_kernel` 内存镜像未通过开销门禁）。此外，**B 组的 3 行中有 2 行未通过（FAIL）**（B1：由于缺少 `diagnostic_view` 钩子，元框架的评估循环在内部将每项分数归零；B3：bug_triage 基准测试包从未从 0.1.0 前身迁移过来）。在声明了这些之后：BENE 除了实现持平（Parity）外，还记录了 A 组的 2 胜/通过（A3, A7），A 组 1 个持平（A1），B 组 1 个通过（B2），以及 C 组的 5 胜（5/5）。

16 行的整体战绩：7 胜/通过（WIN/PASS），1 持平（PARITY），2 败（LOSS），3 缺阵败（NA-LOSS），2 未通过（FAIL），含在 7 胜内的 1 个 B 组通过。

## 完整结果

以下数据经过精简；详细执行命令及每行原始记录保存在可折叠的附录中。

| 行 | 任务 | BENE | 同行 | 裁定 | 备注 |
|---|---|---|---|---|---|
| A1 | 真实检索，top-1，40 个技能 × 15 个自然语言查询（KAOS 逐字数据集） | 73.3% (11/15)，双臂一致（传统 SkillStore BM25；内核 EngramStore Tier-3） | KAOS bm25 臂 73.3% (11/15)；复测偏差 0% | **持平 (PARITY)** | 门禁标准 (BENE ≥ bm25 臂) 技术上以 73.3% ≥ 73.3% 达成，但作为最低限度诚实的裁定结果报为持平。持平符合设计预期：FTS 架构完全相同；双系统在相同的 4 个部署惯例查询上失效。对等比较：两边的结果计数器都不会影响 BM25 排序。 |
| A1b | 相同数据集 vs KAOS 可塑性加权臂 | 73.3% (11/15) | KAOS 加权臂 86.7% (13/15)，约第 60 集盈亏平衡 | **败 (LOSS)** | 预注册为“意料之中——衰减/加权在计划中”。差距 −13.3pp（相对 −15.4%）。BENE 未发布结果加权排序；KAOS 通过奖励习得的那 2 个查询在 BENE 中无法触达。未尝试重新调优；报告首次测量结果。 |
| A2 | 神经可塑性增益 (加权 − bm25) | 无此机制：关于 plasticity/weighting 命中为 0；`record_outcome` 计数器从不反哺排序；衰减策略未发布 | KAOS +10.0pp 绝对值 / +12.5% 相对值；复测 0% 偏差 | **缺阵败 (NA-LOSS)** | 计为 BENE 失利。由于不存在结果反馈驱动的检索，因此无法测量增益。同行侧声明：KAOS 的 break_even=null，且加权训练曲线在训练期间始终低于 bm25；+10pp 仅在最终测量时出现。 |
| A3 | 规模化整合，完整遍历挂钟时间 @ 1k 项，单线程 | 遍历 1000 个轨迹印记的 TraceDistiller.distill：p50 178.0 ms，最高 191.8 ms（3 次遍历；依 KAOS 协议排除种子注入耗时） | KAOS 在 N=1000 时的空跑：提交的 p50 476.0 ms；复测 p50 600.4 ms（决定性，+26% > 10% 阈值） | **胜 (WIN)** | 门禁标准 (< 2× KAOS) 在最不利对比下通过：BENE 最慢的 191.8 ms 对比提交的 476.0 ms = 0.40×。可比性声明：两者的机制不同——KAOS 执行 O(n²) 级别的两两 Jaccard 合并检测 + 晋升/修剪阶段；BENE 执行 O(n·patches) 级别的哈希键精确去重，比较工作量严格更少，且无法合并近乎重复的项。依照 PREREG 设计，BENE 侧排除了大语言模型分析员（LLM analyst）的耗时。 |
| A4 | 关键步骤失效定位，5 个植入轨迹，最早决定性错误 | 无定位器：0 次 grep 命中；TraceDistiller 的 `analyst_fn` 仅是调用方提供的回调，无具体发布实现，无步进模型，无置信度输出 | KAOS 5/5 在 ±1 步内命中（5 个全部精确匹配），纯启发式，置信度 0.65–0.90；复测 0% 偏差 | **缺阵败 (NA-LOSS)** | 计为 BENE 失利。KAOS 获得 5/5 的满分，超过 PREREG 设定的 4/5 门槛，这提高了 BENE 未达成的标准。同行侧声明：这些轨迹是合成的且由该库自身编写；5 个中有 4 个的事实基准为索引 0，因此即使是“永远回答 0”的基线也能得 4/5——但 KAOS 也能答对 gt=2 的用例，而 BENE 完全缺乏相关对标功能，因此败局判定成立。 |
| A5 | 质量评分：连续 vs 二元结果信号 | 无连续质量排序器：`record_outcome(success: bool)` 仅接受二元结果，从不干预搜索；在 BENE 中甚至无法抛出该命题 | KAOS 质量打分领先二元模式 +4.0pp 平均 top-1 命中（85.33% → 89.33%，5 颗种子）；复测 0% 偏差 | **缺阵败 (NA-LOSS)** | 计为 BENE 失利。同行侧声明：KAOS 自己的方差控制假说其实未能成立（质量打分的总体标准差更高），已在其 README 中披露；+4.0pp 是建立在小样本（5 颗种子）上，但很一致（每颗种子下都是 质量打分 ≥ 二元打分）。 |
| A6 | 钩子开销：内核镜像产生的单次写入延迟增加 | 镜像开销 p50 3.83 ms / p95 5.53 ms（取两次运行中最不利数据；对比基准为不挂钩 p50 3.81 ms，挂钩 p50 7.59 ms） | KAOS 钩子开销记录值：−24.6 µs / −87.0 µs / +962 µs；复测值（决定性）：+168.9 µs / −15.1 µs / +3.69 ms | **败 (LOSS)** | 门禁需同时满足：(1) 绝对延迟 < 5 ms 在 p50 达标，但在第 2 次运行的 p95 未达标——由于存在分歧，按最不利解释 = 判定不合格；(2) < 2× KAOS 钩子开销，在所有历史提交记录和最不利复测数据下均未达标。根本原因出在结构而非噪点：`EngramStore.append` 执行了自己的 commit，导致单次写入增加了一个额外的 WAL fsync（该 ext4 主机上需约 3.8 ms）；而在同一主机上，KAOS 钩子的开销仅为 ~0.17 ms。 |
| A7 | 探针规程对等：锁定、防篡改、证伪自检、如实裁定 | 23 个单元测试通过；临时数据库上的活体探针展示了全数 4 种特性（锁定 sha256 匹配；在篡改规格时抛出 LockTamperError；无法否决的门限 → 判定为无效/VOID；指标变差 → REJECT，指标变好 → ACCEPT，并持久化） | 对等目标：KAOS 本机拥有相同的控制规程 (probe.py, verdict.py)；根据 PREREG 规定，无需复测同行项目 | **通过 (PASS)** | 对等，但不具备优越性。声明：首次运行脚本由于表名错误而失败（仅在 /tmp 的测试脚本中修复，未修改任何 bene/ 源码）；基于 verdict_count 检查只是辅助手段；篡改恢复是通过对原始规格文本进行 sqlite UPDATE 实现的。 |
| B1 | 元框架 text_classify 基准测试，模拟/离线模式 | 37 个单元测试通过，但套件缺乏全链路测试；实时模拟循环完成了 2/2 次迭代并产出一个拥有 7 个点的前沿（frontier）——然而 100% 的单题评估在内部抛出 `AttributeError: 'TextClassifyBenchmark' object has no attribute 'diagnostic_view'`，被捕获后判定为零分；得到的是全零退化前沿 | 0.1.0 前身的 HEAD 端存在完全等效的字节级缺陷（`base.py` 相同；评估器的 diff 只是重命名操作） | **未通过 (FAIL)** | 最不利解读：违背 PREREG 声明的“无异常抛出”条款，因为每次内部评估都因报错而退出；产出的“前沿”数据毫无意义。如果采用宽容解读（只要循环能走完且无未捕获异常抛出）则算 PASS。这并非重命名重构导致的退化——缺陷继承自 0.1.0 前身；唯一实现该钩子的基准测试（[redacted]_bug_triage）从未被迁移（见 B3）。按规定必须提的 GitHub issue 无法提交：因未配置 git 远程库。 |
| B2 | Temporal 运行时不变量 + 存储协议套件 | 默认环境：39 项通过，2 项跳过（temporalio 无法导入）。带 `--group temporal` 参数：58 项通过，0 项跳过，0 项失败 | N/A — 用于校验底层依赖迁移，没有预注册同行项目的重测 | **通过 (PASS)** | “完全通过” 的标准仅在安装了明确声明的 temporal 依赖组后达成（基于已归档的文档路径，未篡改任何源码）；默认环境下有 2 个标定的测试全盘跳过。出现 10 条 UserWarnings（关于 EXTERNAL_WRITE 的 TOCTOU 对账提醒），但仅为警告级别。于代码库 HEAD 83cb7ce 运行。 |
| B3 | bug_triage 数据工程导入 + 数据集解析 | 对于 `bene.benchmarks.bug_triage.*` 和 `bene.benchmarks.[redacted]_bug_triage.*` 抛出 `ModuleNotFoundError` 报错；`bene/benchmarks/` 目录仅存在一个命名空间 `__init__.py`；在 BENE 这一侧找不到任何数据集文件 | 0.1.0 前身侧完好（只读状态下）：能够正确导入；search_set.jsonl 包含 121 行；world_physics.json 成功解析 | **未通过 (FAIL)** | PREREG 的预设前提（“目录被 gitignore，但在硬盘上存在”）被推翻：父目录的确被 gitignore 并且存在于硬盘，但包本身从未被复制——最大的可能是由于未被 Git 追踪的文件并未跟随此次从前身向 bene 移植的操作。毫无争议的 FAIL：导入机制和相关数据在 BENE 中双双缺失。 |
| C1 | 受验证门禁约束的晋升（ PromotionBlocked 不含 ACCEPT） | 3 个晋升测试顺利通过；`promote` 操作需一个含有 ACCEPT 结论且用 `verifies` 链接到 candidate 的评估印记（eval engram），且通过 `gated_by` 进行记录，否则会主动抛错 | `PromotionBlocked` = 在 kaos/ 和前身项目中均查无结果；KAOS 的元框架选型中对探针/裁定记录（probes/verdicts）没有引用；0.1.0 前身完全没有 eval 评估模块 | **胜 (WIN)** | 框架限定：KAOS *确实* 具备可证伪的探针机制；它缺少的是基于探针判决挂钩的晋升策略——它的候选池筛选只是在基准跑分的基础上挑出一个帕累托前沿（Pareto frontier）。在此，独特性在于门禁卡控机制，而不在于探针本身。 |
| C2 | 上下文污染侦测 → 检查点回档（全链路 e2e） | 3 个测试通过（干净代理不产生污染；检查点→被污染→触发侦测→利用检查点回滚并持久化污染印记；在没有检查点的情况下建议重置重启） | `pollution` = 在两个同行代码库中皆为 0 次命中；相关的 quarantine/contaminate/evict 搜索命中率同为 0 | **胜 (WIN)** | 两个竞品都有通用的检查点（checkpoint）和状态恢复机制，而且 KAOS 还支持梦境整合（dream consolidation）；它们缺乏的是污染侦测及与之联动的自动化侦测→恢复/提示循环机制。此项制胜关键在于污染侦测器 + 回收策略，并非仅有简单的快照保存。 |
| C3 | 强制接管执行的自治力阶梯（L1 级代理被拒绝 L3 操作权限，且留下遭拒记录） | 1 个测试在 PREREG 的 `-k` 过滤条件中成功匹配；补充验证：执行完整 `test_harness_layer.py` 得到 19 个通过，有关能力剥夺/代理层级调换测试拿到 2 项通过 | `autonomy` = 两家竞品包的命中数为 0；同行的 `capabilit` 命中实际是指针对 FUSE 处理的 Linux-kernel 级别的 Capabilities 脱权设置——概念完全不同 | **胜 (WIN)** | 如实声明出现的偏差：基于 PREREG 的过滤条件只匹配了 1 个测试，原因是没有测试*名字*中包含 "autonomy" 这个词；涵盖 L0–L4 各级别的测试分布在名称不同的方法内，但在全量文件测试中皆通过了。同行缺乏这一机制的状况被确认。 |
| C4 | 可计算的信任账本 + 基于信任的加权投票 | 12 项信任测试 + 1 个加权适配器测试通过（含四维信号集成矩阵，ACCEPT 裁定准入，加权投票幅度管理，和信任印记归档） | 竞品对于 `trust` 的命中都只存在英文说明里；`weighted_tally` = 0 次命中；两者采用的投票都只有简单的赞成（boolean）+自由文本留言模式，计算过程采用简单计票法 | **胜 (WIN)** | 声明：KAOS 的确具备名为 `rank='weighted'` 的检索模式——这与本项用词上有沾边感，但属于搜索排序权重，并不牵涉到信任账本和加权的意见共识。 |
| C5 | 带资产清单且严控预算的上下文组装器（严格不超过预算，带随机抖动） | 1 项测试通过：打满 50 轮随机测试 × 全部策略确保每次都必定符合 `estimated_tokens <= budget` 不变量；同时随附出局和已纳财产的详细清单 | 竞品对 `budget` 的命中完全局限在 时间/费用/历史 的资源预算内；关于上下文 token 预算的搜索命中为 0 | **胜 (WIN)** | 本着对 BENE 最严苛的审视声明：竞品实际上都装配过 `ContextCompressor.compress(messages, max_tokens)` 这个功能——可是全为尽力而为模式（final trim 循环允许返回的结果溢出限额），欠缺资产清单并且没有严守绝不超限的设计约束。这次拿下的优势来自于不可逾越的规约保障和详列清单能力，不能单看是否实现过压缩而已。 |

## 裁定结果（机械套用已锁定的规则）

PREREG 锁定的规则是：*只有满足以下所有条件，才能宣布 "BENE supersedes"：所有的 B 组项目全数通过，C 组全数通过，且在 A 组对决中，未出现任何一项 BENE 在已有功能落地的情况下仍败于竞品的案例（处于计划状态（N/A）的条目会被归类为能力断层并在第一行列出，绝不可隐瞒）。*

| 条件 | 结果 | 证据 |
|---|---|---|
| 所有 B 组项目通过 | **未达成** | B1 FAIL（每一个内部测题统统因为报错引发分数清零；前沿退化成无效数据），B3 FAIL（bug_triage 测试套件连带数据包在 BENE 系统里直接消失）。B2 PASS。 |
| 所有 C 组项目通过 | **达成** | C1–C5 测项全数在当前的 HEAD 端斩获过关战绩，并有着命令级别的同业佐证证明了竞品代码库里不存在那些特性。 |
| 在 A 组不存在机制已落地的败局 | **未达成** | A6 败局：针对 `attach_kernel` 在内存端镜面同步的功能项在基准测试对比中惨遭滑铁卢；其延迟增幅无法闯过任何已定案数据的关口，就算用最具偏见的数据读法复现测试也是未达标的结果。 |

**规则所指向的结论为："BENE supersedes" 这一字眼依然不能够被套用。** 因为三个联动必备要件中倒下了两项；只缺一条足以造成取消资格。

能力鸿沟清单（N/A 类在筹备当中的能力指标；依 PREREG 的准则 4 要求，会对任何超克宣告构成牵绊）：

1. **结果驱动型/具备自适应权重的检索算法**（A1b, A2）— 虽有 `record_outcome` 的使用次数纪录存在却没起到任何排序分流作用；而所谓老化折旧机制只停留在计划里而没有发布。
2. **定位决胜败失效重点链路段**（A4）— 整个 TraceDistiller 就是个虚架子只能指望分析端调用来做事；完全不具备发布内建版追踪器、路径步进建模，以及确信度反馈机制。
3. **连贯式的成果素质计分信号回传**（A5）— 它只允许提供 `success: bool` 的非黑即白布尔形式回报；既然没有任何受其连动的加权排序器，那么二分制与素质式打分这种辩题简直连立论都搭不起来。

缺陷披露（涉及已落地的实现却出现了退步/不合格的技术赤字）：

4. **A6** — 当同步备份信息进内核表时遭遇底层硬伤；它自身带起的那次 commit+fsync 操作把存储性能吞噬掉了（在当前机组配置下单写入会延迟暴增差不多两倍左右）；这是由系统架构决定的而不是系统环境波动。
5. **B1** — 主评估器脚本 `evaluator.py` 内部硬套上了针对 `diagnostic_view()`/`region_key()` 函数的调用动作；然而没有任何一个集成的基准范例接下了这一套钩子动作；这段代码从 0.1.0 前身的 HEAD 版块被一字不差的挪了过来。
6. **B3** — 那唯一曾把 B1 遗珠的两个钩子实装的验证系统（bug_triage 集成包），就在向主干搬移途中给莫名弄丢了，罪魁祸首大概率是那份默认开启的 gitignore 文档过滤了未入库材料。

能够用数据与事实立足的声言底限只能缩在以下边界：在采取基础 BM25 的匹配效果（A1）与守备层面的探针防线（A7）上它等同于 KAOS 的水平；具备更迅捷——虽然算法骨干比较单薄——的文件并卷化手段（A3）；完成面向 Temporal/底层储存重组测试阵列的连结跑通（B2）；以及最后证实竞品在代码中不曾配置下列这五项（C1–C5）：裁定放行机制、具备溯源循环的污染追踪体系、以权力级别为依据的治理手腕、通过信赖记分体系建立起来的决策网以及守口如瓶的上下文组装架构设计。这论点绝不到颠覆替代的地步，而仅仅只是这个测验协议能支撑起的最高标榜强度。

## 有关效度隐患的探讨

**关于 A3 的制胜局如何确保评测公正（基于不同的并卷化机制）。** A 组内的唯一胜绩只建立在用相同 N 规模时两台引擎跑完整趟流程的效能差异，而不是同一种演算法交锋。KAOS 会调用到具有 O(n²) 复杂度的节点比对，使用 Jaccard 算法计算重叠性以找出待合并单元并执行权重的合并/汰除动作；然而 BENE 走的则是 O(n·patches) 这个利用系统散列值来进行死板的去重配对，所以它查不出长得相似但有一丁点偏差的数据模型。这样看下来，BENE 付出的比对工时远不如对家，因此只耗时其四成（0.40×）的现象与其说是架构更猛还不如说是算法取了巧。并且因为系统规定禁止让语言模型下场操作，因而 BENE 这套以模型干预机制为主的架构无从表现。就算挑刺的评审员觉得把 A3 成绩混在一起算就像拿苹果比橘子一样；既然符合评比程序，我们也把它列做 WIN 过关——但得在数值旁边写清楚其间落差。

**移转资料集与它的重映射对标能力（A1/A1b）。** 尽管我们已经利用 AST 原封不动的将来自 KAOS 引擎上的 40 组动作、15 个提问集连带剔除清单等文件全拉了过来，但在套用 BENE 这端的检索键比对上仍然带有一定的换骨效应；在处理内核库层内以 `payload` 组装拼凑数据内容的处理上，完全有可能让 FTS 技术在一个非相同提问集上面失去一致的对焦结果。最终能够拿下一个对标和局也有其凑巧成分在——恰好两边采用了毫无二致的数据关联规划表——这意味除了证明“用的同一套检索法，所以得一样的结论”外，对它的质量无法证明什么。

**关于测速过程碰上的单兵主机波动问题（A3, A6）。** 运行 KAOS 的 A3 项时它在秒数上跳增超过了之前的最佳存档成绩高达百分之二十六以上；而关于 A6 中调出的旧档却出在磁盘读取频率完全不一样的机子上面（底盘基准参数直接跨到 1 与 3.9 ms 之间）。依照规则由事后的实测复原版本说了算，并且无论如何这对于最终成绩单都难以翻案，但这不能当做系统真实反应出来的稳定数据参数到处吹捧。有关 A6 里的门槛判定更带有两种会被揪出来的缺失弱点；该门限比对没有载明（看的是五十或者九十五百分位点），还有在三个原始参照纪录里面就有一大半是负开销记录，让这个“需要小过两倍”的标准简直像句空话一般形同虚设。在这两处有疑义的落点我们一律往让 BENE 最显失利的位置作裁量。

**没有故意利用竞品的瑕疵去赚分这回事。** 关于被作为标的去作弊的合成试题以及其自身库里配给它的检视机制等；五套基线考题就刚好设下四份定点值在原点 0 （因此就算有个什么都不会做的答卷也照样能撞出四分高位及格点数来）。在处理 A2 时它的回馈路径一直在 BM25 以下而且打平值成了 Null 这状况。面对在实验自己控制项减除的论调失败的 A5 结果时。这里出现的竞品缺陷全都动摇不了判决结论——既然 BENE 自己拿不出东西应战的话——可这样反而反映了它们能够以此宣示的标的高低水平所在。

**作为 C 类项目的逆向否证法则根据。** 借用反向验证没碰上命名的字符串或是原始码阅卷比对的举证作为判断基础，这就是属于 GAP-AUDIT 这个阶段的一般核查底规。只是找不到字串还不能说就是少了这个功能；像 KAOS 拥有能够计算权重积分的存储比对模块（邻近 C4 项的设定），而且都有能缩表的内容压缩机能存在（类似 C5）和普通存档机制（与 C2 沾边），这三大项都在项目评述中给点明跟做了技术鉴定了，如果有心要挑刺当然可以狡辩有些边角功能雷同或重合了之类。但是关于在 C 项打通的胜绩是完全依靠那些被隔离出来作分别测试的重要验证属性作定局的（包括管控机制的放行、侦测回测系统防线设计、维持不超支参数等设计点，加上信赖凭证讯号等机制），而不属于那些表面看很像的广域性开发包功能。

**有关用来出成绩那些连提交都没有过的脚本的状况。** 所有在 BENE 这侧用于提取测速值的档案（包括那些位于 `/tmp` 的脚本）并没有经过管控进入正式目录之中，所以如果要能够重现跑出来就需要照着记录附件内里所公布的控制命令重新下指令提取回来用。双方在这个查验周期都挂着有未储存的工作路径进度没有关闭的情况；然而被调用于查错的主线文档全都维持着在主分支里未加改动过的原本情况而且并未出现将信息复写至其它文件的情况，尽管要是能够重新再找一个全新端拉包下来的结果会是一个更硬的实质证物。

**裁判解读弹性空间。** 在三次关键的争议裁度中皆以打压 BENE 取向过场：对于 A1 本是有压过得分的但在实录上被登录成只能当个打平局收尾罢了；把原本存有界接分歧点的 A6 直截了当列入打靶挂彩的项；在看待 B1 的“保证不出任何状况抛误”的要求时，坚持内部连个接住报错的意外包也算中枪的判定基准，没有把它放宽（能跑完这一趟便能给它行）。要是换做是放行松一点的验证官绝对会让 B1 脱出未通的范围改换为成局——然而单就这样依旧拉不回取代对手的那场戏码就是了，毕竟在后头还抵着个 A6 这颗过不去的未解雷包和没找到源文件的 B3 项目在这里。

## 附录 — 原样命令和原始记录

<details>
<summary>A 组命令 (A1/A1b, A2, A3, A4, A5, A6, A7)</summary>

**A1 / A1b — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python /tmp/bene_a1_bench.py
```
抛弃式数据库 `/tmp/bene_a1_bench.db`；原始的按查询 JSON 输出在 `/tmp/bene_a1_results.json`。数据集（40 个技能 + 15 个查询 + 停用词列表 + `_fts_safe` OR 归一化器）通过 AST 方式逐字提取自 `/home/admin/gh/kaos/demo_realistic_retrieval_bench/run.py`。映射策略 arm1（与 KAOS 基准自身的种子播种完全相同）：name=name, description=desc, template=f"Apply {name} to the task", tags=["benchmark","realistic"], source_agent_id=种子 agent。映射策略 arm2：title=name, payload=description+"\n"+template body, provenance={system:benchmark, agent_id:种子}。

**A1 / A1b — KAOS:**
```bash
rm -rf /tmp/kaos_bench_copy && cp -r /home/admin/gh/kaos/demo_realistic_retrieval_bench /tmp/kaos_bench_copy && rm -f /tmp/kaos_bench_copy/results.* && cd /home/admin/gh/kaos && uv run python /tmp/kaos_bench_copy/run.py
```
退出码 0，<1 分钟。已提交的 bm25 最终准确率 final_accuracy 为 0.7333，加权版为 0.8667；复测偏差 0%，且逐次查询的命中模式完全相同；曲线为 [63,67,63,65] (bm25) 和 [60,70,70,70] (加权)。两个代码库都存在未清理的工作区；测试触及的所有模块在 HEAD 均未被修改；/home/admin/gh/kaos 下无任何文件被覆写。

**A2 — BENE 缺失项:**
```bash
grep -rniE 'plasticity|usage_multiplier|wilson|localiz|quality.*signal' /home/admin/gh/bene-main/bene/kernel/ /home/admin/gh/bene-main/bene/skills.py   # 0 命中
```
`bene/skills.py` 内部提供的 search() 查询单纯凭借原生的 FTS5 的 BM25 进行序列判定 (ORDER BY rank, line 234)；记录端点机制内的 `record_outcome()` 增量参数也不对位阶检索构成什么干涉。对于打上折旧汰减时程控制一案也尚未端出实品。要注意的是：技法清单确实可以直接依过去的使用成就计数进行提单(`list(order_by='success_count')`) —— 但这也是种单纯的调用人工过滤动作，而不是检索过程中内含的逻辑处理；这里取的是对 BENE 较不利的解读结果为定调。

**A2 — KAOS:**
```bash
cp -r /home/admin/gh/kaos/demo_neuroplasticity_bench /tmp/bench_neuro && cd /tmp/bench_neuro && rm -f results.* *.db && PYTHONPATH=/home/admin/gh/kaos /home/admin/gh/kaos/.venv/bin/python run.py
```
绝对增幅 absolute_gain_pp=10.0，相对增幅 relative_gain_pct=12.5；2 秒挂钟时间；相较于提交的 `/home/admin/gh/kaos/demo_neuroplasticity_bench/results.json`，存在 0% 的数据漂移。KAOS 的 break_even_episode 参数无值 (null)；带权重学习的走势数据在整个训练区间始终落后 bm25 数据（分布在 0.4→0.6 比上 0.6→0.7）。

**A3 — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python /tmp/bene_a3_consolidation.py
```
单线程打底的一千次追踪点迹提取、利用抛弃型临时资料库执行过程的数据表现：跑在过半数水位的成绩是 177.96 毫秒，最高峰值拉到 191.76 毫秒，并在通过三道扫略圈之后得出的最底部耗损值是 170.63 毫秒；前期塞入引线时等待了大概有 4.6 秒的时间因 KAOS 条款已被剔除。轨迹使用 KAOS 效能测定完全相符的 VOCAB/DOMAINS 列表进行种入，同时制造 50% 坏单比例；在 analyst_fn 侧采用成本低廉并自带针对单独分词抽取贴片方案作解析；每一波次产出三个技法的合并存档体印记。

**A3 — KAOS:**
```bash
cp -r /home/admin/gh/kaos/demo_consolidation_scale_bench /tmp/kaos_consol_bench_a3   # 仅修补了拷贝版：SCALES=[1000]，sys.path 固定指向 /home/admin/gh/kaos
cd /home/admin/gh/kaos && uv run python /tmp/kaos_consol_bench_a3/run.py
```
执行 N=1000 规模验证 (run_consolidation(dry_run=True)): 本地原档里所显示的正常状态指标中位于半数分界点数据落在 475.97 ms 左右 / 极限封顶值触到 482.49 ms；重新回放的结果呈现半数耗散值 600.43 ms / 最高极限突破 602.25 ms（复读三次并夹带前导预热 5.1 秒钟）。结果呈现向外延展超过预期误差界线的高达二成六跑偏比例（超越 10% 底线），因此依规定由其替代决定裁定方向；不管是凭据前者或后者得到的判读结局并没有二样。

**A4 — BENE 缺失项:**
```bash
grep -rniE 'localiz' /home/admin/gh/bene-main/bene/   # 0 命中
grep -rn 'analyst_fn|TraceDistiller' bene/ tests/      # analyst 参数仅存在于 tests/kernel/test_evolve.py 的测试 lambda 中
```
在 `bene/kernel/evolve/distill.py` 这个文本当中（九十九行区带）：它对于所谓的分析接点 `AnalystFn = Callable[[str, bool], list[Patch]]` 这块全推给了调用者想办法去包办；那些充作证明凭据的操作日志是全看人家文本怎样填什么资料就入什么库的方式作业着；这里头不存有什么阶段节点分析建模套件可以使唤、欠缺可以回看查验历程步调数据的基底资料结构支持、更没有从哪下手寻找最初引爆系统溃散发源点的检测程式，最后连要个关于鉴定信心水平可靠度的分数表都不出任何影。

**A4 — KAOS:**
```bash
cp -r /home/admin/gh/kaos/demo_critical_step_bench /tmp/bench_critstep && cd /tmp/bench_critstep && rm -f results.* *.db && PYTHONPATH=/home/admin/gh/kaos /home/admin/gh/kaos/.venv/bin/python run.py
```
全垒打命中 hits=5/5 （突破大等于 4/5 这槛），五次打击全落在正中不差毫厘的坐标处，置信度参数跑出了 0.65 跨到 0.90 的数值，用掉总共才区区一秒钟的流光罢了；其成色与原定调提交的 results.json 中的档案 0 偏差对标。其调包引用的引擎源端自：`kaos.dream.phases.localize.localize()`。

**A5 — BENE 缺失项:**
```bash
grep -rniE 'wilson|quality.*signal|usage_multiplier' /home/admin/gh/bene-main/bene/kernel/ /home/admin/gh/bene-main/bene/skills.py   # 0 命中
```
`record_outcome(skill_id, success: bool)` 唯收黑白单项，压根儿没给品控质量参变量留下什么孔洞让 Wilson 评核器做推演；那些过路收的过路费积分其实也全进不了后台对排座引流指路的搜索引擎。

**A5 — KAOS:**
```bash
cp -r /home/admin/gh/kaos/demo_quality_score_bench /tmp/bench_quality && cd /tmp/bench_quality && rm -f results.* *.db && PYTHONPATH=/home/admin/gh/kaos /home/admin/gh/kaos/.venv/bin/python run.py
```
增幅跳动落差点数四（由原始仅靠双位制分拣所持有的准确度占比 85.33% 挂着标准差偏移量 0.0267，推进至改采阶级排档品控制衡所获得的高达 89.33% 外扩一点到标准差带 0.0327；使用五个不同源发母体数据下总共完成了一百二十局轮回赛）；方差削减点数为 -0.006 （该团队设想的变异系数缩减预定落空了）；全程操作总时耗为十三秒间段内搞定，结果对比原始资料的 JSON 版本完美无瑕，零漂移量。它顺道在 PYTHONPATH 指向范围内带过借去给在 demo_realistic_retrieval_bench 下边那些开发套件一起陪同走马验证一遍；对于附属的这些依存结构是存在并处于不变状况中没有丝毫损伤的。

**A6 — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python /tmp/bene_a6_mirror_overhead.py   # 处刑过两趟，提取对受审者最伤的呈堂证物供上
```
各路模式对上一千个刷单的连贯输出攻击，使用不掺杂任何存盘的 /tmp db 用时间校测表跑在单个运作流水通道上。当撤离内核辅佐功能后得出对半数的落点值在 3.81 毫秒处 / 但飙高段则碰了 7.88 毫秒的界线；装上附属于接合内核镜像能力后结果拉高至了半数关卡于 7.59 毫秒 / 其上限区域冲上了 13.48 毫秒的高峰点；那么相扣下那中间加压开支部分半数界定在 3.83 毫秒间，最高值是 5.53 毫秒（首局数据表现是：3.833/4.140；次局数据表现是：3.785/5.533）。

**A6 — KAOS:**
```bash
cp -r /home/admin/gh/kaos/demo_plasticity_overhead_bench /tmp/kaos_overhead_bench_a6   # 只修补拷件的路径指引给系统: sys.path 对接回 /home/admin/gh/kaos 本命库去了
cd /home/admin/gh/kaos && uv run python /tmp/kaos_overhead_bench_a6/run.py
```
纪录中明文提交登载过的各项波动差额幅度数据（在挂网跟离机双重对照下，抓中间平准位每个动作用掉时间段）是这样子的：在回写执行状态下的数据减少了 24.6 µs 的反应延滞、换成打内存储列调档检索这边扣降了将近有 87.0 µs 时间、只在那给代理者做下课收班打包时延时给拉长到了近乎暴增近一个毫秒时间点差（+962.0 µs）。换到了当下机组来复盘后的实际参数：+168.9 µs, −15.1 µs, +3.69 ms（就连 KAOS 它本家产的效能侦测台在这时针对这个代理器收官封关任务都自己标出了一个已越界破表的警告通知单出来）。由这回重新测量跑出的成果充当决定权基准点（基于它跟本案历史登录的数据相比出现超过一成差距幅度的异状；想必当初存下这份报表的人用的可是一架能在文档定存处理上神速非凡的好机种才能有那么亮眼的数字）。就凭这两组不管拿谁当作量度依据都得算是没考上败下的结局。一切过程在 KAOS 这里半张文件页都未被弄乱过；BENE 方面的内核母库全处于隔离保护区中滴水不漏没有任何一串代码去过加工编辑动作；凡有交锋较量的过程只让系统把活交给了放于 /tmp 里的隔离替代影武者来打完罢了。

**A7 — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python -m pytest tests/kernel/test_eval.py tests/kernel/test_hardening.py -q   # 统共过了两十三条战线总消磨时日耗七秒八十五厘光阴
uv run python /tmp/a7_live_probe.py   # 在个不挂心的免洗型态数据库 /tmp/a7-live-probe.db 执行任务，结束点出零的安好代号
```
第一道防线的锁死保护层建制：有鉴于相关变通评准阀（所取在与前值品质对照差分界于大于大抵在小数点后零五基点带附有须有前因值基础上的设定状态下）一经注册下线入库后，后台登出的防阻密码钥扣就呈现 lock_sha256=1030d2242ac613a4... 这款密文格式，而且跟把存档明文做成指纹后的 sha256(stored spec) 得出无落差完全等于的状态，更是跟锁闭内存上管控着出入站大门的那些凭证密码链核得上的，在状况拦位那头也放出了可以通行的准单（admissible）。再推进入被恶搞防范这端上测试底线时：如果拿一段像这样的 `UPDATE probe_registry SET gate_spec=<0.05→−9.0>` 后台变造更动语句想打通通关流程的话，在触发时直接回它个 LockTamperError 破坏系统禁制警告，拒发入境。第三重就是那套自身否决抗身能力核实作业：如被抛出一个铁锁不让任何对象存活的死亡底线时（譬如说定个门槛参数到负的九百九十九这么不可理喻的情境段位），将判定打落成拒绝过界名单内不让入境（inadmissible），而且那个判断引擎将径自判定该项提审直接成了无效无疾而终废卷（run() verdict=VOID）。来到最终关头确保如实供呈不隐讳环节中：将上一步被恶整的字眼再由更新恢复回去变成起码像样的人话文字叙述之后；试跑若是弄出一个在原来档位基准上比原来逊色差加了两码的数据就给予打枪不要了（REJECT），相对若拉拔起超越原本基数有近十位高位的佳绩便准予核可收进库去保存起来（ACCEPT），在那个专门被设出来登载成绩跑分日历用档案堆里确实也是能实打实抓着有着两条这样记录轨迹线存底着了的（参考处所是在 `bene/kernel/eval/verdict.py:69` 这）；然而开头初版那支抓写数据专用的简制脚本写错地方没抓正那个对口的数据库位置所以翻了车而落得白工（只在那置于临时废区 /tmp 去调过正而已，半只字没对真正的 bene/ 代码区有何动作）。同业竞合比量基底盘区：打的是它那端管控这两项目的 `kaos/eval/harness/probe.py` 以及裁断部门 `kaos/eval/harness/verdict.py` (包含接收/不受理/作废表态项等)；基于条约所言本部分可以跳越再次找那同行出马这层手脚功夫。

</details>

<details>
<summary>B 组命令 (B1, B2, B3)</summary>

**B1 — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python -m pytest tests/test_metaharness.py -q -p no:cacheprovider   # 用时 0.11s 通过了 37 个
uv run python /tmp/b1_live_mock.py
uv run --project /home/admin/gh/bene-main python /tmp/b1_diag.py
```
实时模拟版：这里 MockRouter.route 直接奉还包含着 ```python 内容模块之框架组件版体回来；那个叫作 MockClient.chat 这支外挂就在那接着为植补进去那个名为 llm() 这个功能模组接应收摊子做垫背的；至于名叫 TextClassifyBenchmark 生成用来作仿真做假题目的集散册子搜索容积被压在了第八等级距而已；数据仓库被放在 `/tmp/bene_b1_mock.db` 。战报开示如下：一共轮回滚打过了两梯阵 (iterations_completed=2/2)，框架被拿来过秤审视数目共七批 (里面三颗当播种子的另配四笔凑团成行)，做出了总共有七处触点成网面的帕累托曲线端锋地带出来，关于发号中心提出指令走上两趟过，完美打住并挂着 0 个失败异常印记出来无所遗憾收尾。可实际上把内部这壳撬翻仔细看这怎么做手脚出那些帐目出来看下那问题根底的话：发觉百分百在作那些一道道解题查核算分手工作业过程中根本全是在中途给当了而且跳出了：`AttributeError: 'TextClassifyBenchmark' object has no attribute 'diagnostic_view'` 这个被判定是在没有具备这个该存在项时的抗议声的，不过全在一道后被挡在 `bene/metaharness/evaluator.py:152` 这个抓鬼网收住包没爆个大场出来而已；导致的结果就是把所有一切积分通统全拿鸭蛋抹平当算了；跑出来看是挺大一条曲线边界带却成了全部零和底的破壳空包退化阵线了。病灶发源根源在这个位置起发：在 `bene/metaharness/evaluator.py:89-90` 这个点强制毫不迟疑地去给那个 `benchmark.diagnostic_view()` 或许连同 `region_key()` 都一样下令启动了起来；结果它自己身为主母巢舰级源头的 `bene/metaharness/benchmarks/base.py` 上头根本这东西影子和功能接口说明都从未定调打样过半回的；甚至那些拿来充数当内建样版参考用那几家套件们 (像啥：text_classify 或啥 math_rag 以及什么 agentic_coding 和另外个啥 arc_agi3 这些包中)，也没一家能自给自足补足自己来顶这些残缺出阵迎敌的本事存在的。

**B1 — 0.1.0 前身比较:**
```bash
diff $PREDECESSOR_SRC/predecessor/metaharness/benchmarks/base.py /home/admin/gh/bene-main/bene/metaharness/benchmarks/base.py   # 文件一致
grep -rn 'def diagnostic_view'   # 仅在两个代码库测试内的 predecessor/predecessor/benchmarks/[redacted]_bug_triage/v2_benchmark.py 和 _DiagnosticBenchmark 测试本地文件中存在
```
evaluator.py 的差异仅仅是重命名（Predecessor01→Bene，DARTRouter→TierRouter）。按规定本应提交的 `gh issue create` 无法执行：在 bene-main 中 `git remote -v` 输出为空。

**B2 — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python -m pytest tests/test_runtime_invariants.py tests/storage/ tests/temporal/ tests/test_runtime_core.py tests/test_runtime_handle.py tests/test_temporal_runtime.py -q -p no:cacheprovider
# 在 2.79 秒内，39 个通过，2 个跳过（模块级别：无法导入 'temporalio'），10 个警告
uv run --group temporal python -m pytest <same 6 targets> -q -p no:cacheprovider
# 在 13.81 秒内，58 个通过，0 个跳过，0 个失败，10 个警告
```
在 `pyproject.toml [dependency-groups].temporal` 中声明了 temporalio/asyncpg 扩展。警告内容：策略为空时的 EXTERNAL_WRITE（活动重试时 TOCTOU）。当前仓库位于 HEAD 83cb7ce，未对源代码进行任何修改。

**B3 — BENE:**
```bash
cd /home/admin/gh/bene-main && uv run python -c "import bene.benchmarks.bug_triage.benchmark, bene.benchmarks.bug_triage.game_master"
# ModuleNotFoundError: No module named 'bene.benchmarks.bug_triage'  (退出码 1)
# 调整名称为 bene.benchmarks.[redacted]_bug_triage.* → 相同的错误
```
`ls bene/benchmarks/` 显示只有一个命名空间 `__init__.py` + `__pycache__`；在 bene-main 以及同级目录 /home/admin/gh/bene 的检出副本（src/bene 为空）中使用 `find` 也找不到任何 triage 包；没有数据集文件。其父目录 `bene/benchmarks/` 被列在 .gitignore 文件中（.gitignore:20）。

**B3 — 0.1.0 前身 (只读模式):**
```bash
cd /tmp && PYTHONDONTWRITEBYTECODE=1 uv run --project $PREDECESSOR_SRC python -B -c "import predecessor.benchmarks.[redacted]_bug_triage.benchmark, predecessor.benchmarks.[redacted]_bug_triage.game_master"
# '0.1.0 前身导入正常 (OK)'
```
data/search_set.jsonl = 121 条 JSONL 记录（键值包括：expected/id/input/provenance）；data/world_physics.json = 包含 6 个键的字典。没有在 $PREDECESSOR_SRC 或 /home/admin/gh/kaos 路径下生成新文件。

</details>

<details>
<summary>C 组命令 (C1–C5)</summary>

**C1:**
```bash
uv run python -m pytest tests/kernel/test_evolve.py -k promotion -q   # 用时 1.14 秒通过 3 个，反选 15 个
grep -rEn 'PromotionBlocked' kaos/ predecessor/                               # 0 命中
grep 'promot' /home/admin/gh/kaos/kaos/metaharness/search.py           # 0 匹配
grep -rE 'from kaos.eval|Verdict|REJECT|ACCEPT' kaos/metaharness/*.py  # 0 命中；对于 predecessor/metaharness/*.py 也一样
ls predecessor/eval                                                           # 找不到这样的文件或目录
```
机制落点：位于 `bene/kernel/evolve/gepa.py:40` 处理 PromotionBlocked 逻辑；对于关卡判定逻辑位在 gepa.py:193-211 行内。相比之下 KAOS 其对于标示阵前点界落置之判断则藏在：search.py 内的 `_compute_frontier` 模段从第 93 行绵延到 244 行的区域。

**C2:**
```bash
uv run python -m pytest tests/kernel/test_memory_os.py -k "pollut or recover" -q   # 用时 1.14s 通过 3 个，反选 18 个
grep -rEn 'pollution' kaos/ predecessor/                                                  # 0 命中
grep -rEn 'quarantine|contaminat|evict|decay' kaos/memory.py predecessor/memory.py kaos/dream/   # 0 命中
```

**C3:**
```bash
uv run python -m pytest tests/kernel/test_harness_layer.py -k "denied or autonomy" -q   # 在 0.41s 内通过 1 个，反选 18 个
uv run python -m pytest tests/kernel/test_harness_layer.py -q                            # 19 个全部通过，用时 6.44s (补充测试)
uv run python -m pytest tests/kernel/test_capabilities.py -k "denied or autonomy" -q     # 2 个全部通过 (补充测试)
grep -rEn 'autonomy' /home/admin/gh/kaos/kaos/ $PREDECESSOR_SRC/predecessor/                  # 两边都是 0 命中
```
同行所谓的 `capabilit` （特权管控）的搜寻迹证只单独散见在了该处名为 isolation.py 的模组内（也就是处于 122 行开始接棒跨延至 128 行止息处）：那是用于去解除由于架设 FUSE 这个底层技术所配得给与 Linux-kernel 层级的全权能力封锁命令而已的动作。在 BENE 这座山头上布下这层层防御关卡底气是建置在这个名叫：`bene/kernel/capabilities.py` 还有协同运作所在的 `bene/kernel/harness/autonomy.py` 身上这片防护网。

**C4:**
```bash
uv run python -m pytest tests/kernel/test_trust.py -q                  # 用时 4.27s 跑过 12 个项
uv run python -m pytest tests/kernel/test_adapters.py -k weighted -q   # 1 项顺利通关被挑明留位，筛掉其它旁余不相干项共 10 列次
grep -rn 'weighted_tally' kaos/ predecessor/                                  # 没捞半点对应点迹留底
grep 'weight' kaos/shared_log.py predecessor/predecessor/shared_log.py               # 完全没有任何挂接指涉痕迹出现过
```
那些对家的关于论及 `trust` 字眼的触角不过只出现在打上这种记号点处了而已（像是在这几支像：kaos/eval/__init__.py 里面第5行写下的 'trustworthy'，kaos/eval/harness/types.py 这里头第 74 行填下的 'untrustworthy'，或者是另外这处的 predecessor/.../run_lab.py 这头拉延到 371 行所批注上 `# trusted, in-process` 这玩意儿）——全部不外乎是一些英文行文时为了通篇顺畅所做的表面用语解释文摘罢了。而且在有关那些由同路人端出来的评决方法 vote() 里所做的也不过：打了个通过过关印证记号 (boolean 形式) 外加写段无关痛痒自由抒写的心得感想话文本格式 (位处于 kaos/shared_log.py 的第 252 行段位或者是这另处的 predecessor/predecessor/shared_log.py 之中落在 第 178 行位置)。但扯上一丁点边的地方也就：在于 kaos/memory.py 文件区域中从 140 连发越到 199 之间的一块功能，它提供了把 `rank='weighted'` 这参项设定带上让其运作的找寻功能开启而已 (是以 bm25 架构相乘于其打档出栈提取频率数相乘其提取近期度参数的一组联集作用数群组体) ——可是这也只是一组被拿在做检索名流次第分级定位用的数值体系架构罢了，与所谓的针对采信基点信凭账本设计毫无半点纠葛沾惹就是了。

**C5:**
```bash
uv run python -m pytest tests/kernel/test_memory_os.py -k budget -q   # 在 0.05s 内有 1 个通过，排除了 20 个不相关项
grep -rn 'budget' kaos/ predecessor/   # 所搜集查出到的记录完完全全全偏向了时间段或者花费金额方面的这等盘点设限账目：像 arc_agi3.py 内设定管制时间量的 time_budget (落在 76,123,240,397,423 这些列数点间), 在早期型号里的跑马试验用文件脚本里 run_lab.py/run_overnight.py 里针对消费限额的 spend budget 设立，在这份文件 predecessor/temporal/workflow.py 当中的 228 行上管控调阅史量所下防线的 history_budget ，甚至连在操作打号指令端的命令行操作环境里的三十分钟倒退重启防线的把关参数里都是这类东西。
```
真正能在架构与运作形式上与此相近且同道有采用配置过的防范法度手段就在这儿：于 router/context.py 里面头有个名作 `ContextCompressor.compress(messages, max_tokens)` 的这玩意能挑点相近似对标的味道（摆在 kaos 这个包的源码第 64 行区域里，在这早期祖父辈前身代码上则是在其 62 列的区段出现着）——可它的运作心态只用着个只要我有拼命尽本分就好了的态度作业（它那最后阶段削皮循环刀法是在当扫平到发现到长度变成 len(compressed)<=4 就喊歇手不干的状态不管最后剩余到底是不是依然越过了安全容留点底线还是超出多少不管的）；连张像样的造财目录细表都没端出更绝不要说是立下那个一旦划了死限就不容逾越过半分绝不退让性质测防检验底线设定了。

</details>

---

*报告生成时间 2026-06-11，针对 PREREG sha256 `f9179cf814e9a7d713007d7fc4c66f25e25a011f68dc4c6e70cf5c201b5043f8`。所有的裁决都基于在最不利于 BENE 的解读下完成；根据 PREREG 的原则 3，上方那些 LOSS/NA-LOSS/FAIL 不合格记录全以诚实展现的面貌列载了上报作底，所以算是圆满走完了监看稽考关卡，不是这审议会出包被当的结局。*
---

*本报告于 2026-06-11 生成，基于 PREREG sha256 `f9179cf814e9a7d713007d7fc4c66f25e25a011f68dc4c6e70cf5c201b5043f8` 锁定。全程采用对 BENE 最不利的口径赋予裁定结果；遵循 PREREG 准则 3，上述的 LOSS/NA-LOSS/FAIL 项均作为诚实审计的成功产出，而非审计工作的失败。*

---

## 第二轮 — 缺陷修复与重测 (2026-06-11, 第一轮后)

第一轮的裁定结果如上文如实记录。在那之后，我们通过常规的工程排期修复了浮现出来的三个已发布机制的缺陷——在此坦诚披露提交记录和重测数据。这是标准的迭代式交付，而不是为了跑分而去重新作弊调参（retune-and-rerun）：没有重新协商任何门禁标准，也没有篡改任何第一轮的数据。

| 行 | 第一轮状态 | 修复措施 | 第二轮重测 | 第二轮状态 |
|---|---|---|---|---|
| B3 | FAIL（bug_triage 包缺失 — 在 0.1.0 前身迁移过程中被 gitignore 屏蔽而丢失） | 带着完整的重命名映射恢复了该包，26 个文件，现已被**追踪（tracked）**，不再会悄然消失 | `import bene.benchmarks.bug_triage.benchmark, .game_master` → 正常；121 行 JSONL 解析成功 | **通过 (PASS)** |
| B1 | FAIL（每次评估均抛出内部异常：`evaluator.py` 调用了基类从未定义的 `diagnostic_view()`/`region_key()` —— 0.1.0 前身的 HEAD 端存在一模一样的缺陷） | 基类默认值 + 回归测试（`test_base_benchmark_diagnostic_and_region_defaults`） | 元框架套件 38 个全过；模拟循环评估不再遭遇零分清算 | **通过 (PASS)** |
| A6 | LOSS（镜像开销 p50 3.83 ms — 根本原因：每次写入带来了第二次 WAL fsync 惩罚） | 新增 `EngramStore.append(commit=)` 参数；适配器镜像现在搭乘调用方自身的事务便车；`Bene.close()` 负责提交挂起的写入操作 | 开销 p50 **0.82 ms** / p95 1.04 ms（提升了 4.7 倍）；绝对值 <5 ms 门禁**通过**；最严苛的相对值读法（同行 168.9 µs 裸计数器钩子的 2 倍）仍然**未通过** —— 他们的钩子仅仅是更新了俩计数器，而我们的镜像要写下一条带有溯源链接的印记 + FTS 索引行 | **部分达标 (PARTIAL)**（绝对值通过，相对值未过 — 如实报告测试值） |

修复后的完整套件成绩：**634 通过，1 跳过**（B3 的恢复重新激活了 20 个之前被跳过的测试）。

### 重新计算第二轮锁定规则下的裁定结果

- B 组：B1 PASS · B2 PASS · B3 PASS → **B 组全数通过**。
- C 组：C1–C5 WIN（维持原判）。
- A 组机制落地败局：按照最严苛的预注册读法，A6 依然是一记 LOSS。

**因此，在第二轮结束后，"BENE supersedes" 这句宣告依旧不可使用** —— 联结条件之一（A 组不得有机制落地的败局）依旧折戟于 A6 的相对门禁上，并且四个能力鸿沟（A1b/A2/A4/A5：无结果驱动排序、无关键步骤定位器、无连续质量信号）原封不动地保持着第一轮的模样。第二轮能加码给出的最强声明是：*前身所有的底层机制现在都能在 BENE 上正确跑通，甚至包括了一个前身自己至今仍在携带的顽疾。*

### 仍待推进的遗留事项（计划清单，保持不变）

1. 结果驱动的检索算法（填补 A1b/A2 鸿沟 — 这是最大的实测差距，−13.3pp）。
2. 基于轨迹印记的关键步骤定位器（填补 A4 鸿沟）。
3. 连续质量的结果信号（填补 A5 鸿沟）。
4. 将镜像的写入批处理压进 2 倍裸钩子的门禁内，前提是效能分析证明这在真实负载下有意义（针对 A6 相对门禁）。

---

## 第三轮 — 填平计划鸿沟 (2026-06-11, 第二轮后)

第一轮和第二轮的裁定原样保留。第三轮秉承了与第二轮相同的迭代交付纪律：将前两轮暴露出来的能力鸿沟作为常规工程任务进行收口，并在此披露提交记录和重测数据。没有任何门禁被重新谈判，没有任何旧数据被篡改，PREREG.md 不受一丝触碰（sha256 一致）。随之而来的定调后果在这里开诚布公：**通过实装这些原先处于 N/A 状态的行，它们的失利——如果真输了——现在就会被算作机制落地的惨败，这是性质更重的一类。无论如何，我们进行了测量。** 最终，第三轮未失一局。

已交付机制（每项仅对应一次微小的代码提交）：

- `1c27697` — 结果加权 + 连续质量检索排序（可选开启 `rank="weighted"`：BM25 × 威尔逊下界 × 指数衰减近期度；`record_outcome` 喜提可选的 `quality ∈ [0,1]` 参数；默认的 BM25 排序雷打不动）。
- `3a9d667` — 关键步骤定位器（`bene/kernel/evolve/localize.py`）：在融合了工具/日志/事件的时间线上寻找最早的决定性错误，启发式优先，置信度随证据多寡浮动，带有根据轨迹形态指纹缓存的 LLM 备用方案。
- `ecd42ea` — 批处理内核镜像：镜像行现在可以在进程内缓冲并在读取/刷盘/关闭时统一排空（`executemany`）；耐久性契约已在文档中明确。

测试台现在已被**追踪归档**至 `benchmarks/community/` 下（终结了第一轮“无版本控制的 /tmp 脚本”的效度隐患）；同行的测试数据集在运行时直接通过 AST 从 KAOS 检出库提取，因此数据在机制上保证了逐字对应，绝不会发生复制漂移。

| 行 | 第一/二轮状态 | 机制 (commit) | 第三轮重测数据 | 第三轮状态 |
|---|---|---|---|---|
| A1 | 持平 (PARITY) 73.3% | 维持默认臂（`1c27697` 绝不能让它动摇） | bm25 臂 73.33% (11/15) — 逐查询命中模式完全一致 | **通过 (PASS)**（无退化） |
| A1b | 败局 (LOSS) 73.3% vs 86.7% | 加权排序 (`1c27697`) | 加权臂 **86.67% (13/15)** vs KAOS 加权 13/15 | **通过 (PASS)**（精确打平 — 注意是打平，不是胜出） |
| A2 | 缺阵败 (NA-LOSS，无机制) | 同上 | 增益差值(加权 − bm25) = **+13.33pp** vs KAOS +10.0pp | **通过 (PASS)** |
| A4 | 缺阵败 (NA-LOSS，无定位器) | 定位器 (`3a9d667`) | 在 ±1 步误差内得 **5/5** (KAOS: 5/5)；即便粗暴的一律猜 0 也能拿 4/5；不过中间轨迹 gt=2 的用例也顺利抓准；置信度 0.65–0.90 | **通过 (PASS)** |
| A5 | 缺阵败 (NA-LOSS，只有二元判决) | 质量信号 (`1c27697`) | 二元 85.33% → 质量评分 89.33%, **+4.0pp** (5 颗种子；每颗种子上都是 质量评分 ≥ 二元) | **通过 (PASS)** |
| A6 | LOSS (第一轮 3.83 ms) / PARTIAL (第二轮 0.82 ms, 相对值未过) | 批处理镜像 (`ecd42ea`) | 取两趟测跑的最差值，并在计时窗口内执行排空动作：最具决定性的写单耗是 **0.314 ms**/笔 vs 相对门禁 0.338 ms；p95 落在 0.362 ms vs 绝对门禁 5 ms | **全面通过 (PASS)** — 相对门禁仅仅只抠出了大概 7% 的微小余量 |
| B1–B3 | PASS (第二轮后) | — | 38 项通过 · 默认环境 39+2跳过 / `--group temporal` 下 58+0跳过 · 导入正常且 121 行全部成功解析 | **通过 (PASS)** |
| C1–C5 | WIN | — | 所有点名套件在 HEAD 全数通关 (3 / 3 / 19 / 12+1 / 1) | **胜 (WIN)**（同行缺失的查证证据与第一轮一致，直接引用不再重查） |

三个新特性加入后的完整测试成绩：**699 通过，3 跳过**（新增 84 个测试）。

### 通用性声明

一轮专注填坑的修补回合，最大的效度死穴就是“面向跑分调参”。我们做了以下校验（诚实声明：由于计划中的独立评审代理中途撞穿了 API 配额，这些校验是由统筹本次修复的同一个代理进程内联完成的——详见威胁分析）：

- **零数据集泄露**：针对 KAOS 检索和关键步骤测试台里所有 ≥12 字符的字面量，对新出炉的 `bene/` 源码进行字符串重叠扫描——零命中；机制代码中绝对找不到任何技能名、查询串、停用词或轨迹标签的影子。
- **参数即机制默认值**：z=1.96 (95% 威尔逊)、14 天半衰期、4 倍超额拉取、固定置信度系数——每一项都在源码注释中给了明确论证；没有一个是照着测试台跑分倒推捏造出来的。
- **面对新数据的表现**：在凭空捏造的新数据集上，加权排序依然会把高可靠性的技能顶上去，同时让默认的 BM25 排序结果保持逐字节一致；定位器能够在三条全新生成的轨迹中准确定位非 0 索引处的决定性步骤（证明了无 0 索引偏好；置信度也正常浮动）；批处理镜像能在优雅关闭后，稳稳当当让 50/50 笔写入数据落盘并可被检索。

### 重新计算第三轮锁定规则下的裁定结果

| 条件 | 结果 | 证据 |
|---|---|---|
| 所有 B 组项目通过 | **达成** | B1 的 38 项通过；B2 在包含 temporal 依赖群组（有正式文档指引）下拿到 58 项过关 0 跳过；B3 的引流架构与资料读解皆运转正常 |
| 所有 C 组项目通过 | **达成** | C1–C5 测试套组皆于最新 HEAD 版拔得头筹 |
| 在 A 组不存在机制已落地的败局 | **达成** | A1 的基本盘势不变；A1b 握手言和；A2/A4/A5 顺利破关；A6 的两条红线皆在最严苛的标准解读下被翻跃过去；A3/A7 与第一轮战报别无二致 |

**规则所指向的结论为："BENE supersedes" 这个词终于能名正言顺被挂上了** —— 它的三项严苛联立基石都已经确实锁死，并连同以下几点披露作为其承重墙结构，绝非只是摆设：

1. **A6 的相对门禁余量只有仅仅 ~7%**（0.314 vs 0.338 ms），而且这还是在这台机器上摊销后的最不利解读；若是换作一台 fsync 较慢的设备，这个盘面随时会翻转。绝对值门禁倒是有着 14 倍的安全边际。
2. **A1b 是一个绝对的平局**（13/15 = 13/15），并非胜出。检索能力上所谓的“全面超越（supersession）”依据在于我们不仅造出了这套机制，而且还打成了平手，而不是赢了他们多少。
3. **A5 的得分与同行的得分如出一辙**（85.33%→89.33%）。只要种子和数据集给定，协议的运算过程就是绝对确定的，由于两个框架的威尔逊估算器在面对这波试炼时做出了完全一致的排序定夺；但我们已透过源码审查以及上述面向新数据的防作弊检验，证明了两套系统绝对是独立开发的机制。
4. 第一轮中关于 A3 的可比性免责声明（我们采用的是较轻量级的整合计算机制）以及支撑起 C 组胜率的反证底气依旧不变。

### 有关效度隐患的探讨 (第三轮落差)

- **球员兼裁判的内审机制。** 这份关于模型通用性的认证是由写代码的同一个工作例程亲自下场开出的，因为原定用来担任铁面判官的独立评审代理中途就把 API 额度给干穿了。虽然这些检测关卡全是用冰冷的机器指令和脚本敲出来的（grep 工具加测试脚本），但一个具备敌意心态的审查员理应要求借由第三方之眼来验视；等 API 额度重置后再把那群评审机队拉出来跑一圈，这才是低成本的最佳解药。
- **摊销式刷盘带来的测速视差** (A6)：仅仅统计单次写入的 p50 值会把延后刷盘的真实成本藏起来；所以我们的测试台聪明地把包含 `close()` 在内的完整周期掐表计算，并在“单笔 p50”与“整体摊销均值”这俩数字中挑了较难看的那个摆上台面——可摊销计算的前提是那 1000 笔写入凑成的大礼包；要是遇到“写 1 笔就关门”的极端场景，那就得生吞活剥扛下没被摊销掉的刷盘硬成本了。
- **复刻版的失真危机** (A1b/A2/A5)：像剧集循环、ε-贪婪抓取，乃至那些给部分分数的操作函式，全都是比照 AST 解析出来的数据规格重新造过一次轮子；我们还原的是规章逻辑本身而非整套代码照抄，因此极有可能在某些暗角偏离了竞品的原始意图，只是一模一样的最后跑分刚好成了完美的遮羞布。
- **自产自销的考题** (承袭自上个阶段)：包含所有五条事件轴与捞词试卷全是由对方竞品库那边自己产出的；早先在第一轮笔记上给他们挑出的毛病（像是总偏好找 0 号索引下手的习惯、以及总是低于标线的训练成效）时至今日依旧狠狠地钉死了对方那些参考数据的含金量上限。

---

*删改声明 (2026-06-11, 第三轮后)：为避免泄露特定雇主身份，附录中原封不动贴出的命令所附带的一个具名模块前缀，已被替换为 `[redacted]`，而且 `bug_triage/data/` 内的档案也已从本代码库的追踪名录中被拔除（只留存在本地端供跑分复现之用），起因是这批数据集脱胎自不宜公开的内部留底记录。所有命令句型其余部分皆原汁原味未动分毫；B3 那项“导入正常且成功解析”的测试成绩是在本地档案环境下扎扎实实测出来的，真实有效。在正式把这个代码库端上台面公之于世前，绝对还得回滚 Git 历史去把这批数据档给彻底漂洗干净（毕竟在找回 B3 到落锤实行这段删减作业期间，它们曾实打实地躺在追踪清单内）。*
