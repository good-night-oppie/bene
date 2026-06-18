# 从 48% 狂飙到 83%：BENE v0.2.0 如何让多 Agent AI 研发实现全自动化

*一场实录：看看 Meta-Harness 是如何全自动地、在短短 15 轮迭代内、仅烧了 $0.14 就摸出了霸榜的 prompt 策略*

---

你为了给手头的分类器搓出一个完美的 prompt，可能已经人肉熬了三天。你试了思维链 (chain-of-thought)，又试了硬塞 few-shot 案例，接着又让它扮演 "资深工程师" 角色。准确率死死卡在 74%，你麻了。你又跑了一个变种，还是 74%。再跑一个，依旧 74%。

这就是所谓的停滞天花板 (plateau problem) —— 这种局往往极其隐蔽，等你意识到时，你早已深陷泥潭。

BENE v0.2.0 就是来一脚踹碎这块天花板的。看好了。

---

## BENE 到底是啥？

[BENE](https://github.com/good-night-oppie/bene) 是一个将 6 篇顶级 LLM 研发前沿论文在工程上进行合成落地的、纯本地跑的、多 Agent 编排框架。每一只 agent 都拥有一个基于单体 SQLite 文件拉起的、绝对物理隔离的虚拟文件系统 (VFS)。自带全量不可篡改的审计流水。自带快照与一键回滚。彻彻底底的零云端依赖。

它的头牌杀招就是 **Meta-Harness (演化脚手架)**：一个全自动的搜索闭环，它把 prompt 工程降维成了一道纯粹的数学优化题，旨在为任何大模型任务找出最能打的 prompt 策略。定好你的任务，喂给它点数据，敲一句 `bene mh search`，然后去喝咖啡。等你回来时，迎接你的是一个已经排好座次的帕累托前沿 (Pareto frontier) 变种榜单。

v0.2.0 新引入了 **CORAL** 机制 —— 三层协同进化的猛药。它能让这场搜索战役爆发出恐怖的智商，尤其是在大模型陷入瓶颈打转的时候。

---

## 垫底的科研血脉

在看实战演示前，有必要交代一下引擎盖底下装了什么。BENE v0.2.0 融合了四篇经过同行评审的硬核科研成果：

- **[Meta-Harness](https://arxiv.org/abs/2603.28052)** (arXiv:2603.28052, Stanford/MIT/KRAFTON) — 搜索循环本体：让一个充当 proposer 的进化引擎去生啃完整的执行流水，然后提出结构上更为优秀的脚手架变种。
- **[MemPalace](https://github.com/milla-jovovich/mempalace)** — 极其紧凑的 AAAK 标记法，能在零质量折损的前提下，把 proposer 的上下文负担硬生生砍掉 57%。
- **[CORAL](https://arxiv.org/abs/2604.01658)** (arXiv:2604.01658) — 停滞雷达、心跳反刍以及多 agent 协同进化，直接把进化突破率拉高了 3–10倍。
- **[EvoSkills](https://arxiv.org/abs/2604.01687)** (arXiv:2604.01687) — 代理验尸官 (Surrogate Verifier)：在信息绝对隔离的前提下进行翻车诊断。

这绝不是在模型 API 外面包的一层薄薄的壳。这是一次彻头彻尾的、从地基建起的工程落地，它把 2025–2026 年最凶悍的多 agent 搜索技术，全部搬到了你的本地机器上。

---

## 靶场实战：代码评审 (Code Review) 严重度分类

**任务：** 丢给你一条 GitHub 的 PR 审查评论，把它归入以下四个严重度级别之一：

- `BLOCKER` — 致命命门，合并前必须修掉 (安全漏洞、脏数据、逻辑崩盘)
- `IMPORTANT` — 重点问题，尽快修 (性能拉胯、屎山反模式)
- `STYLE` — 锦上添花 (命名规范、格式化)
- `PRAISE` — 夸你写得好

**弹药：** 200 条人工标注好的 PR 审查评论。大模型裸跑 (Zero-shot) 的基线准确率：**可怜的 48%**。

---

## Step 1: 圈定靶场 (Benchmark)

```python
# benchmarks/code_review.py
LABELS = ["BLOCKER", "IMPORTANT", "STYLE", "PRAISE"]

EXAMPLES = [
    {"comment": "SQL query is vulnerable to injection — must fix before merge",
     "label": "BLOCKER"},
    {"comment": "This N+1 query will cause issues at scale",
     "label": "IMPORTANT"},
    {"comment": "Variable name `x` is not descriptive",
     "label": "STYLE"},
    {"comment": "Nice use of early returns here, much cleaner!",
     "label": "PRAISE"},
    # ... 剩下 196 个例子
]

def evaluate(harness_fn, examples=EXAMPLES):
    predictions = [harness_fn(e["comment"]) for e in examples]
    correct = sum(p == e["label"] for p, e in zip(predictions, examples))
    return {"accuracy": correct / len(examples), "n_correct": correct}
```

这就是 benchmark 契约的全部。BENE 只需要你丢给它一个 callable (可调用的函数) —— 喂给它输入，它吐出带有分数的 dict。

---

## Step 2: 扎营，鸣枪

```bash
bene init
# ✓  初始化 bene.db
# ✓  刷入 v4 版本的 schema 血肉
# ✓  唤醒驻场的知识库 agent [bene-knowledge]

bene mh search -b code_review -n 15 -k 3 --background
# ✓  挂载靶场: code_review  (200 题, 4 个分类)
# ✓  放出了专职跑搜索的 agent [01JMHSRCH-code-review]
# ✓  后台 worker 进程已拉起 PID 14832
```

**bene.yaml** 里掌管着 CORAL 的生杀大权：

```yaml
provider: claude_code        # 狠狠地白嫖你的 CC 订阅，API 费用归零
model:    claude-sonnet-4-6
compaction_level: 5          # 砍掉 57% 的上下文，换取 100% 的质量不流失
stagnation_threshold: 4      # CORAL 转向机制：如果连跪 4 轮就强行逼它转向 (Pivot)
consolidation_every: 6       # CORAL 技能心跳频率
```

---

## Step 3: 火种跑分 (Seed Evaluation)

```text
[seed 1/3]  zero_shot         acc=0.48  cost=12.4   96/200 ✓
[seed 2/3]  few_shot_2        acc=0.54  cost=18.7  108/200 ✓
[seed 3/3]  cot_basic         acc=0.61  cost=24.1  122/200 ✓

火种摸底跑分完毕。初始前沿矩阵 (Frontier): 3 个身位
最强火种: cot_basic (acc=0.61)  —  搜索战役将从此起步
```

仅仅是加上了最糙的思维链 (chain-of-thought)，就已经把 zero-shot 按在地上摩擦，硬拔了 13 个点。此时的 proposer 手里已经攥着三份带血的执行流水，可以开始推演了。

---

## Step 4: 陷入绞肉机 (The Search Loop)

```text
[iter 1/15]  role_engineer        acc=0.67  +0.06 ↑  进化成功 (IMPROVED)
[iter 2/15]  role_engineer_v2     acc=0.71  +0.04 ↑  进化成功 (IMPROVED)
[iter 3/15]  rubric_detailed      acc=0.69  ─  相比榜首退步了 (regression)
[iter 4/15]  few_shot_balanced    acc=0.74  +0.03 ↑  进化成功 (IMPROVED)
[iter 5/15]  few_shot_4x          acc=0.73  ─  稍逊风骚
[iter 6/15]  chain_contrast       acc=0.74  ─  平了最高纪录，但没能突破
[iter 7/15]  few_shot_role_merge  acc=0.74  ─  stagnant_iters=4 (连跪 4 轮)
```

在 74% 的泥潭里死死卡了四轮。它撞上了停滞天花板。

---

## Step 5: CORAL 暴力转向 (Pivot)

当 `stagnant_iters` (连跪计数) 撞碎了阈值 (4)，BENE 直接在塞给 proposer 的下一份摘要里强行砸进了一块 `PIVOT REQUIRED (必须转向)` 的横幅：

```text
╔══════════════════════════════════════════════════════════════════╗
║  必须转向 (PIVOT REQUIRED)  —  连跪=4  霸榜分=0.74               ║
║                                                                  ║
║  已经被榨干的老路：                                              ║
║    • 角色扮演 (工程师/审核者) — 天花板卡在 0.74                    ║
║    • Few-shot 硬塞 — 每类塞 1-4 个，边际效应递减                    ║
║    • 带对比用例的思维链 (CoT) — 摸到了天花板，但没法突破           ║
║                                                                  ║
║  强制任务：请拿出一套八竿子打不着的全新流派出来。提示：          ║
║    • 两步定罪法 (先问是不是 blocker？不是再问是不是 style？)       ║
║    • 动手分类前，先做结构化的属性提取                              ║
║    • 加入置信度校准 + 碰上模棱两可的直接弃权                       ║
╚══════════════════════════════════════════════════════════════════╝
```

想继续交几份换汤不换药的角色扮演变种糊弄过去？没门了。Proposer 被逼着必须推翻底座重来。

---

## Step 6: 撕裂苍穹 (The Breakthrough)

```text
[iter 8/15]  two_step_chain        acc=0.78  +0.04 ↑  进化成功  (转向奏效了！)
[iter 9/15]  attr_extract          acc=0.79  +0.01 ↑  进化成功
[iter 10/15]  two_step_attr_merged  acc=0.83  +0.04 ↑  进化成功  ← 新王登基
```

杀到第 10 轮时，CORAL 的心跳固化机制 (consolidation heartbeat) 被触发：

```text
⟳ CORAL 心跳固化启动  (每 6 轮跳一次)
  正在从这 10 轮的血海里蒸馏可复用的神级操作 (skills)...
  已刻写神技: two_step_decomposition (两步拆解法)
  已刻写神技: attr_grounding (属性兜底法)
```

而那个缝合了 "两步拆解" 与 "属性提取" 的超级变种，一举将准确率轰到了 **83%**。比起 48% 的裸跑基线，这特么硬拔了整整 35 个点。

---

## 膜拜最强变种

```python
SYSTEM_PROMPT = '''You are a senior software engineer reviewing a PR.
Classify the review comment using a two-step process:

STEP 1 — Extract attributes:
  impact:       high | medium | low
  scope:        blocks-merge | should-fix | nice-to-have | positive
  correctness:  yes (bug/security/logic error) | no

STEP 2 — Apply classification rules:
  If correctness=yes AND impact=high  →  BLOCKER
  If correctness=yes AND impact<high  →  IMPORTANT
  If scope=nice-to-have               →  STYLE
  If scope=positive                   →  PRAISE
  Default ambiguous to IMPORTANT.'''

def harness(comment: str) -> str:
    response = llm(SYSTEM_PROMPT, comment)
    return extract_label(response, valid=LABELS)
```

没上向量数据库。没外挂检索。更没搞狗屁微调。这就是一份在结构上碾压对手的 Prompt —— 一份资深 Prompt 工程师可能需要熬上好几天才能试出来的极品。而 Meta-Harness 靠着全自动机器只走了 15 步就把它生生刨了出来。

---

## 算总账

```text
基准裸跑 (zero-shot)   48% 准确率
Meta-Harness 洗礼后    83% 准确率 (硬拔 35 个点)
耗费迭代轮次           15
搜索总耗时             ~12 分钟
API 账单               ~$0.14
制胜绝杀               靠 "两步定罪法" 彻底撕开了 BLOCKER 和 IMPORTANT 之间的模糊地带
沉淀的神技             入库了 2 个可复用套路 → 下一场战役直接站在巨人的肩膀上起步
```

![知识的复利 —— 每一场战役都在滋养下一场；神技与案底在奔跑中不断沉淀](../assets/knowledge-compound.png)

所有的审计记录随时等候你的 SQL 拷问：

```sql
SELECT iteration, harness_id, scores->>'accuracy' as acc, status
FROM mh_attempts
WHERE benchmark='code_review'
ORDER BY iteration;
```

---

## v0.2.0 的大杀器：CORAL 的三层猛药

### 第一层 — 停滞雷达 + 强行转向 (Pivot Prompts)

搜索循环现在会死死盯住 `stagnant_iterations` (连跪轮数)。一旦它击穿了 `stagnation_threshold` 阈值，一堵写满 `PIVOT REQUIRED` 的叹息之墙就会横在 proposer 的脸上，拉出所有已经山穷水尽的废坑，并勒令其必须拿出一套结构性颠覆的新招。

### 第二层 — 叠了三层甲的记忆库 (attempts / notes / skills)

- **`/attempts/`** — 包含每次评估的 `{id, 分数, 死活状态}` 极简浓缩表
- **`/notes/`** — 选填的单轮观后感与日记
- **`/skills/`** — 从尸山血海里爬出来的可复用套路，被死死刻进跨战役的全局知识网里

### 第三层 — 狼群并发，协同进化 (Co-Evolution)

```python
# 放出去 3 只狼，从截然不同的刁钻角度一起围剿同一个靶场
result = mh_spawn_coevolution(benchmark="code_review", n_agents=3)

# 它们各自疯跑，但每隔 2 轮就会碰一次头互通有无
mh_hub_sync(agent_0_id)
```

原论文里的战果：比单打独斗的搜索**高出 3-10倍的进化突破率**。有 36% 最终奏效的突击，是直接踩在另一只狼刚刚趟出的路基上的。

---

## 怎么上手

```bash
git clone https://github.com/good-night-oppie/bene.git
cd bene
uv sync
uv run bene init
uv run bene mh search -b text_classify -n 10
```

如果你想体验极致的协同模式 (让 Claude Code 通过 MCP 直接在你的 IDE 里发号施令拉起战役)：

```json
{
  "mcpServers": {
    "bene": {
      "command": "uv",
      "args": ["run", "bene", "mcp"],
      "cwd": "/path/to/bene"
    }
  }
}
```

然后在 Claude Code 里敲：*"拿 bene 的 MCP 帮我跑一把 meta-harness search，靶场选我的那个情感分析 benchmark，先给我干 5 轮。"*

不用 API key。不用额外掏钱。因为你买的 Oppie CC 订阅本身，就是那台算力澎湃的推演引擎。

---

## 顺藤摸瓜

- [README 首页](../README.md) — BENE 全景大局观和全套文档入口
- [破局战法 (Use Cases)](../use-cases.md) — 更多来自泥坑一线的实战套路
- [核心部件指南：演化脚手架 (Meta-Harness)](../meta-harness.md) — 扒光搜索循环的每一个参数 + CORAL 三层猛药的深度解剖
- [教程：t00 — 端到端速通实战](t00-bene-e2e-walkthrough.md) — 如果你连 BENE 的门还没入，请先退回这里

---

*BENE 能够纯粹靠本地算力强行驱动。没有任何一滴数据会流出你的机器。*

*膜拜科研源头：[Meta-Harness](https://arxiv.org/abs/2603.28052) · [MemPalace](https://github.com/milla-jovovich/mempalace) · [CORAL](https://arxiv.org/abs/2604.01658) · [EvoSkills](https://arxiv.org/abs/2604.01687) · [Karpathy 的 autoresearch](https://github.com/karpathy/autoresearch)*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
