# 演化脚手架 (Meta-Harness)：用搜索算法跑出一个最强脚手架

给 bene 塞一份标注好的数据集，外加一套或几套初始的脚本 (Harness)，然后你就可以撒手去喝咖啡了：一个 AI Proposer 会死死盯着每一份执行流水，亲手改写 harness 代码，并且只有那些在你的数据上跑分确凿变高的变种代码，才会被留下来。

> **只需敲一行命令，就能把平时靠人肉干的 "微调一下 prompt 然后重跑" 的低级循环，彻底拉升为一场有着严密测量、随时可断点续传、且全盘留底的自动化代码搜索战役。**

bene 的这套玩法直接落地了 [Meta-Harness 论文 (arXiv:2603.28052)](https://yoonholee.com/meta-harness/) 里的核心技术；关于出处和可跑的示范代码，去 [血脉渊源和实战靶场](#血脉渊源和实战靶场) 找。在 bene 的世界观里，这被称作 "配种计划 (breeding program)" —— 一场极其考验耐心、跨越数个世代的、专门针对 harness 代码的达尔文式大筛选。

---

## 为什么搜索算法能把人肉调参按在地上摩擦？

你手里那套大模型是个黑盒，它是冻死的。你能掌控的，是外面套的那层脚手架 (Harness)：到底塞什么词进 prompt 里？捞哪些旧例子作弊？带多少上下文陪跑？光是脚手架好坏的差距，就能让同一个大模型在同一个任务上的表现拉开 **6倍** 的鸿沟。

普通人想要把这 6 倍的性能抠出来，靠的是手工作坊式的死力气 —— 改改 prompt，眯着眼睛看看输出，然后再改改。而 Meta-Harness 的降维打击，就在于它把这套手工作业直接做成了全自动闭环。

---

## 打响你的第一枪

针对几个内置的数据集，你可以直接起步搜：

```bash
# 文本分类战役
bene mh search -b text_classify -n 20 -k 3

# 外挂检索 (RAG) 的数学题
bene mh search -b math_rag -n 20 -k 3

# Agent 式的全自动编程
bene mh search -b agentic_coding -n 10 -k 2
```

如果你想拿自己的私家数据集 (比如一份你司的 CSV 或者 JSONL 语料) 来跑，你需要走 Python API 里的 `get_benchmark` 接口 (去抄 [在 Python 里发号施令](#在-python-里发号施令) 那节的作业)。

`-n` 限制的是搜索迭代轮数，`-k` 则限制每轮提议出的变种数量。想看全部的参数？去翻 [把所有开关列在同一处](#把所有开关列在同一处)。

---

## 扒开一场战役的五脏六腑

想要看懂这套杀戮机器是怎么运转的，最直观的办法就是拆解一场实战：教一个分类器去分发工单。

### 1. 你的弹药 (数据)

```python
# 你的家底 —— 贴好标签的真实客诉工单
tickets = [
    {"text": "I was charged twice this month", "label": "billing"},
    {"text": "API returns 500 errors on POST", "label": "technical"},
    {"text": "How do I add team members?", "label": "account"},
    ...
]
```

### 2. 你的火种 (Seeds)

Seeds 就是你的开局底牌 —— 针对这个任务最初始的几种解法。最少得塞一个；多塞几个能让 Proposer 有对冲对比的抓手，学得更快。

**Seed 1 — 零样本盲狙** (最糙的打法):

```python
def run(problem):
    return {
        "prompt": f"Classify this ticket: {problem['text']}\nCategory:",
        "context_tokens": 20,
    }
```

**Seed 2 — Few-shot 硬塞** (硬塞几个最近的案例进去):

```python
def run(problem):
    examples = problem["labeled_examples"][-4:]
    example_block = "\n".join(f"Ticket: {e['text']}\nCategory: {e['label']}" for e in examples)
    return {
        "prompt": f"{example_block}\n\nTicket: {problem['text']}\nCategory:",
        "context_tokens": len(example_block.split()),
    }
```

**Seed 3 — 智能检索** (靠重叠词挑出最像的案例):

```python
def run(problem):
    # 算算词汇重合度，揪出最像的 5 张工单
    query_words = set(problem["text"].lower().split())
    scored = [(len(query_words & set(e["text"].lower().split())), e) for e in problem["labeled_examples"]]
    scored.sort(reverse=True)
    top = [e for _, e in scored[:5]]
    ...
```

### 3. 血肉磨盘转起来了

```bash
bene mh search -b support_tickets -n 10 -k 2
```

就敲下这行命令之后，机器深处会掀起一场怎样的腥风血雨：

#### 第 0 轮 — 给初始火种称重

系统会当场拉起 3 个充当裁判的 evaluator agents，一个 seed 分配一个，全关在死磕的独立 VFS (虚拟文件系统) 小黑屋里：

```text
Agent: harness-01HXY1A...    (零样本那套)
  /harness.py                  ← 脚手架源码本体
  /evaluation/scores.json      ← {"accuracy": 0.45, "context_cost": 20}
  /evaluation/per_problem.jsonl ← 逐题明细
...
Agent: harness-01HXY1C...    (智能检索那套)
  /harness.py
  /evaluation/scores.json      ← {"accuracy": 0.70, "context_cost": 120}
  /evaluation/per_problem.jsonl
```

跑完的分数全都会被汇入**搜索档案馆 (Search Archive)** 里，这个档案馆自己本身也是一个独立 agent 的 VFS 领地：

```text
Search Agent VFS:
  /config.json
  /seeds/seed_0.py, seed_1.py, seed_2.py
  /harnesses/
    01HXY1A.../source.py, scores.json, trace.jsonl, per_problem.jsonl, metadata.json
    ...
    01HXY1C.../source.py, scores.json, trace.jsonl, per_problem.jsonl, metadata.json
  /pareto/frontier.json     ← 战报显示：目前检索那套方案占优
```

在每一份 harness 的案底目录下：

- **source.py** — 变种方案的源码
- **scores.json** — 最终的汇总战绩 (准确率、上下文开销等)
- **trace.jsonl** — 全景式的跑分流水：输入长啥样，标答是啥，生出的 prompt 啥样，AI 给的预测是啥，判题对不对，耗了几个 token。
- **per_problem.jsonl** — 分题目的细粒度账单
- **metadata.json** — 身世档案 (第几代、爹是谁、当时改它的 rationale 思路)

这些 trace 文件才是真正的核心。在原论文的消融实验里，喂给 proposer 完整 trace 所带来的战力，能把那些只喂了干瘪得分或者缩水总结的 proposer 甩开足足 15 个百分点。

#### 第 1 轮 — Proposer 开始狼吞虎咽

紧接着，bene 唤醒了一只极其凶悍的 **Proposer Agent**：它手里握着能够撬开整个档案馆大门的专属工具。

- `mh_ls_archive("/harnesses")` → 把那 3 个案底全拉出来看看
- `mh_read_archive("/pareto/frontier.json")` → 看看榜单，发现检索流确实最能打
- `mh_read_archive("/harnesses/01HXY1C.../trace.jsonl")` → 把第一名的做题流水一题题扒开看
- `mh_grep_archive("word overlap")` → 一条正则，全档扫射

靠着生啃流水，它把出了脉案：检索流虽然能干到 70% 登顶，但一旦遇到了同义不同词的表述就当场抓瞎 (比如 "账单出了笔神秘扣费" 和 "重复收费"，一个词都不重样，overlap 打分直接报零蛋)；而那套硬塞 few-shot 的方案，死穴在于最近塞进去的例子刚好避开了当前需要的正确分类。

它大笔一挥，写下两副猛药：

**Candidate 1 — 聚类强吃。** 先把数据池按分类聚好，然后保证每个分类都硬抽出一个例子喂进去。
**Candidate 2 — 盲猜再查。** 先不带例子裸跑一发猜个大概，拿着猜出来的分类去精准捞例子，最后拿着这些精准例子再跑第二遍做确认。

它会拿着 `mh_submit_harness(source_code, rationale)` 把这两套代码丢出去。但在碰到测试集之前，代码必须得过两道鬼门关 (两级校验)：

1. **AST 静检** — 用 `ast.walk` 查验它是不是合法 Python，且有没有老老实实写明 `run()`。
2. **跑通点火** — 用一道题当靶子真刀真枪跑一遍，但凡报了异常直接毙掉。

没跑通的残次品连上桌的资格都没有。

```text
跑完第一轮后的档案馆:
  /harnesses/
    01HXY1A.../  ← seed: 零样本    (acc=0.45)
    ...
    01HXY1C.../  ← seed: 检索流    (acc=0.70)
    01HXY1D.../  ← 新方案: 聚类强吃 (acc=0.73)  ← 变强了！
    01HXY1E.../  ← 新方案: 盲猜再查 (acc=0.80)  ← 新王登基！
```

#### 第 2 轮 — 踩着新王的尸骨向上爬

再去翻新王 (盲猜再查流) 的翻车记录，它的软肋就暴露出来了：**模棱两可的模糊工单**。比如 "我想要降级套餐"，判给 account 没错，判给 billing 好像也对。而隔壁聚类方案的流水给它送来了灵感：如果把长得极像但分类截然不同的工单 (也就是对比样例，contrastive pair) 同时喂进去，大模型的火眼金睛立马就能拉满。

于是，新一轮的变种出炉了：

**Candidate 3 — 对比校验。** 在第二遍校验时，故意塞一些长得像但分类不同的陷阱题进去。
**Candidate 4 — 标签预热。** 直接在 prompt 开头，把所有分类跟一句话描述全甩给大模型。

```text
跑完第二轮后：
  Candidate 3: acc=0.83, cost=150  ← 刷新了准确率天花板
  Candidate 4: acc=0.77, cost=45   ← 准确率下降，但尼玛便宜了三倍！
  Pareto 帕累托前沿：[Candidate 3 (霸榜准确率), Candidate 4 (霸榜开销)]
```

#### 第 3 到 10 轮 — 复利的暴击

从此往后，proposer 算是开了天眼，每一轮都能俯瞰全局。它平时最爱耍的花招包括：

- 把前三甲拎出来，拆出那些立了大功的代码片段
- 盯着翻车记录使劲看，找出至今没补上的漏网之鱼
- 把原本毫无瓜葛的两套流派硬缝合在一起
- 一刀切中要害，一次只修一个 bug，绝不无脑推翻重写

为了约束它，bene 还在系统 prompt 里塞进了原论文摸索出来的三大军规：

- **连跪后转保守 (Go additive)** — 如果连着几轮都在退步，proposer 就会被锁死在 "只许加东西，不许碰老代码" 的保守模式，大幅压低风险。
- **控制变量法 (Change one variable)** — 每个变种只许改一处地方，只有这样，分数的涨跌才能清清楚楚地算在那个改动头上。
- **溯源对比 (Compare across iterations)** — 逼着它去翻旧账，搞清楚以前的改动到底是帮了倒忙还是真有奇效。

bene 默认 `candidates_per_iteration` (每轮变种数) 设为 **2** (论文里是 3)；因为在工程实测中我们发现：集中火力少提几个变种，比无脑乱撒网的效果要更狠。

### 4. 战事结算

十轮绞肉战打完，系统会给你甩出一份结案报告：

```text
Meta-Harness Search Complete
  Search agent: 01HXY1234AB...
  Iterations: 10
  Harnesses evaluated: 23
  Duration: 847.3s
  Frontier size: 4
  Best accuracy: 0.8700 (harness 01HXY1F...)
  Best context_cost: 35.0000 (harness 01HXY1G...)
```

把登顶的那套代码拽出来看看：

```bash
bene mh inspect 01HXY... 01HXY1F... --db support-tickets.db
```

而且，既然整场战役的每一滴血都留在了 SQLite 里，那你的拷问就绝不止步于一个简单的 summary：

```sql
-- 揪出所有青出于蓝而胜于蓝的变种，看看它们当时是怎么想的？
SELECT h.metadata->>'$.rationale' as strategy,
       h.scores->>'$.accuracy' as accuracy
FROM ... ORDER BY accuracy DESC;

-- 这场大搜索到底烧了我多少 token？
SELECT SUM(token_count) FROM tool_calls;

-- 第五轮的时候，那只 proposer 到底在抓瞎琢磨些什么鬼？
-- (直接读 proposer 的原始会话记录)
```

---

## 只有一个文件，查个底朝天

原版论文的代码，是往平坦的文件系统上一股脑乱拉屎。bene 把它搬到了自己极其洁癖的 VFS 引擎上，以下这几条，你随时可以自己验证：

**物理隔离。** 任何变种代码，全被关在自己私密的 VFS 小单间里执行。再恶毒的 bug 代码也休想染指档案馆，更不可能摸到隔壁兄弟的命脉。

**快照锁死。** 每轮开打前，系统的总状态会被强行打上 checkpoint 快照。要是 proposer 脑溢血或者评估跑到一半断了电，一句话就能时光倒流。

**审计深水区。** 读了哪个文件、写了什么、用了什么工具、改了什么状态，全被一字不漏地夯进 event 日志里。你能完美复原 proposer 当时到底看了啥才拍的大腿。

**SQL 伺候。** 把 grep 丢进垃圾桶吧；你可以用严丝合缝的 SQL 去拷问历史。谁用了 retrieval 流派？每轮烧了多少 token？准确率曲线到底长啥样？一发 query 就能给你答案。

**极其便携。** 所有的兵马 —— 代码、流水、甚至是 proposer 之间的碎碎念 —— 全部死死锁定在一个极其轻巧的 `.db` 文件里。把它甩给你的同事，他们就能拥有整场战役的所有因果。

---

## Proposer 到底能摸到啥？

四件，且仅有四件工具组成了 proposer 的爪牙：

| Tool (工具) | 用途 |
|---|---|
| `mh_ls_archive(path)` | 把档案馆里的陈列列出来 |
| `mh_read_archive(path)` | 强行读取档案馆里的某个死档 (源码、流水、分数) |
| `mh_grep_archive(pattern)` | 把正则当成推土机，把档案馆里**所有**文件碾一遍 —— 极度适合跨代排查特定的死法，或是寻找某项祖传绝技 |
| `mh_submit_harness(source, rationale)` | 掷出新改的 harness 变种 (附带两级鬼门关校验) |

到了后期，档案馆里挤满了各路先辈留下的代码残骸时，`mh_grep_archive` 的杀伤力就体现出来了：只要喂进去一条 `"word overlap"`, `"KeyError"` 或者 `"timeout"`，它就能瞬间劈开所有的文件，把跨代遗传的顽疾生生剥出来，根本不需要你去一个个死翻流水。

---

## 死而复生 (断点续传)

系统崩盘、网络超时或是你手贱按了 Ctrl-C，都绝对毁不掉你跑了一半的战果。每一次试跑、每一条流水和不断外扩的帕累托前沿，早就写进了 `.db` 文件里。一句话，直接从上一次成功结算的世代接着往下打。

### 在命令行里敲

```bash
# 从上次死掉的地方爬起来
bene mh resume <search-agent-id>

# 瞧瞧它到底卡在哪了
bene mh status <search-agent-id>
```

### 用 Python 唤醒

```python
from bene import Bene
from bene.metaharness.search import MetaHarnessSearch
from bene.metaharness.benchmarks import get_benchmark
from bene.metaharness import SearchConfig
from bene.router import TierRouter

db = Bene("search.db")
router = TierRouter.from_config("bene.yaml")
bench = get_benchmark("text_classify")
config = SearchConfig(benchmark="text_classify")

search = MetaHarnessSearch(db, router, bench, config)
result = await search.resume(search_agent_id="01HXY...")

print(result.summary())
```

### 通过 MCP 唤醒

拥有 37 把专武的 MCP Server 同样也暴露出了一把 `mh_resume` 工具，只需塞一个参数就能让它诈尸：

```json
{
  "search_agent_id": "01HXY..."
}
```

在唤醒时，bene 会从 search agent 的 VFS 档案馆里重新拼装出战局，找出最后跑完的那一轮，并一毫不差地继承原先的所有军令 —— 原本的 benchmark、原本的变种生成数、以及原本的优化指标，全都不变。

---

## 任何破模型都能来当 Proposer (v0.2.0)

有的破模型 —— 比如挂着 `claude --print` 的那种 —— 脑子可能被门挤了，一辈子都不会老老实实吐结构化的 tool call，导致它们根本摸不到 `mh_submit_harness` 这把提交武器。bene 自动看穿了这一点并做了极客补偿：一旦系统发现某个 proposer 叨叨了半天却没有动用哪怕一件工具，bene 就会生生去扒它的回话记录，只要找到任何夹着 `def run()` 签名的 ```python 源码块，就会硬行把它当做变种拽进生产线，且一视同仁地接受同等的双重静检。

无论你只会说大白话，还是深谙工具调用，这碗饭 bene 都喂得进你的嘴里。你一行配置都不用改。

---

## 压缩摘要，别撑死大模型 (v0.2.0)

每一轮，proposer 都必须强行消化掉前人留下的每一份 harness 源码、每一个冰冷的跑分和所有的执行流水。如果不做压缩，这至少要耗上 5-10 刀的 tool call；而要是摊上 `claude --print` 这种每轮都强行把前文回滚重播的家伙，它绝对会死在超时的路上。

因此，bene 内置了一套**高度结构化的档案馆压缩摘要 (archive digest)**。它分三路走，每一种数据都能受到针对性的暴烈压缩：

| 数据门派 | 压缩策略 | 实际砍法 |
|---|---|---|
| 分数、头衔 (metadata) | 丝毫不拔 (Lossless) | 原汁原味 (本身体积就不大，而且全都是纯度极高的信号) |
| 源代码 | 0-7 级：不剪；8-10 级：扒光 | 绝对保证 proposer 永远能摸到代码 |
| 分题流水 | 结构化强吃 | 只抽出具体的错误模式 (error patterns)，再挂载 N 个残骸现场 |
| 跑分日志 (Traces) | 暴力过滤 | 答对的题直接滚，只保留答错或者爆炸的现场 |
| 跨轮扯皮对话 | 梯次褪色总结 | 把远古的嘴炮浓缩，只保留近期的原话 |

以下是 bene 用 8 道极其刁钻的测试题测出来的质量保留情况：

```text
Level  0 │ 3727 chars ( 节约 29%) │ 纯度=100%  │ 8/8 题全对
Level  3 │ 2818 chars ( 节约 46%) │ 纯度=100%  │ 8/8 题全对
Level  5 │ 2818 chars ( 节约 46%) │ 纯度=100%  │ 8/8 题全对  ← 这是默认档位
Level  7 │ 1927 chars ( 节约 63%) │ 纯度=100%  │ 8/8 题全对
Level 10 │  184 chars ( 节约 97%) │ 纯度=37.5% │ 3/8 题全对
```

在砍到 7 级之前，100% 的纯信号都被保住了；但如果你作死拉到 10 级，信号的丢失就会像雪崩一样 (只能答对 3/8)。实际上，通过结构化抽取把错误模式硬核地提炼出来喂给它，效果**反而比**粗暴地把几万字的生肉流水全甩给它要好。

在 `bene.yaml` 里一刀切地设置：

```yaml
search:
  compaction_level: 5  # 0 (原汁原味) 飙到 10 (压缩到极致)
```

或者在你的单次战役里微操：

```python
config = SearchConfig(benchmark="text_classify", compaction_level=7)
```

---

## 五大领域，全部抗压测试通过 (v0.2.0)

把默认档位 (Level 5) 拉到分类题以外的领域去挨刀：

| 战场 | 节约的显存上下文 | 信号纯度 |
|---|---|---|
| Classification (分类) | 46% | 100% |
| Code Generation (写代码) | 28% | 100% |
| Research / RAG (搜索检索) | 25% | 100% |
| Tool Calling (调工具) | 25% | 100% |
| ML Training (跑模型) | 18% | 100% |

一旦你强行干到 10 级，每个领域都会遭到毁灭性的信号制裁，存活下来的质量只会剩下 25-37.5% 不等。

---

## CORAL：打破僵局的猛药 (v0.2.0)

任何搜索算法只要跑得足够久，都会像无头苍蝇一样绕着一根柱子打转：proposer 陷入了局部最优的死胡同，不停地掏出大同小异的微调破烂。CORAL ([arXiv:2604.01658](https://arxiv.org/abs/2604.01658)) 祭出了三大杀招来冲破这种停滞天花板，而 bene 把这三招全部接了过来。

### 第一杀招 — 侦测停滞，逼它转向 (Pivot)

如果连续 `stagnation_threshold` 轮 (默认 3 轮) 没能刷新霸榜分数，送到 proposer 嘴边的下一份摘要就会拉起刺眼的横幅：

```text
╔══════════════════════════════════════════════════════════════════╗
║  必须转向 (PIVOT REQUIRED)  —  连跪=4  霸榜分=0.74               ║
║                                                                  ║
║  已经被榨干的老路：                                              ║
║    • 角色扮演 (工程师/审核者) — 天花板卡在 0.74                    ║
║    • Few-shot 硬塞 — 每类塞 1-4 个，边际效应递减                    ║
║    • 带对比用例的思维链 (CoT) — 摸到了天花板，但没法突破           ║
║                                                                  ║
║  强制任务：请拿出一套八竿子打不着的全新流派出来。                ║
╚══════════════════════════════════════════════════════════════════╝
```

想再混一个微调的变种？没门了。一旦看见这块 `PIVOT REQUIRED`，proposer 就必须连根拔起换一条截然不同的路线走。

在 `bene.yaml` 调阈值：

```yaml
search:
  stagnation_threshold: 4    # 连吃 N 轮败仗后强行拔高
  consolidation_every: 6     # 每隔 K 轮把学到的花活收割进技能库
```

或者在代码里：

```python
config = SearchConfig(
    benchmark="code_review",
    stagnation_threshold=4,
    consolidation_interval=6,
)
```

### 第二杀招 — 三层叠甲的记忆体

档案馆里会多出三个极其硬核的目录：

| 目录 | 里头藏啥 | 搞啥名堂 |
|---|---|---|
| `/attempts/` | 每套方案的 `{id, 分数, 状态}` 缩水表 | 方便 proposer 一眼扫穿，免得把源代码塞爆显存 |
| `/notes/` | 逐轮用 markdown 写下的血泪日记 | 这堆日记会塞进下一轮摘要里，逼着 proposer 去反刍自己过去的推断 |
| `/skills/` | 从日记里蒸馏出来的可复用绝技套路 | 会被刻写进知识网 (knowledge agent) 里，拿去当未来的起步 seed |

哪怕是战役进行到一半，也能通过 MCP 直接刻下新学到的绝活：

```python
# 战役胶着时，Claude Code 可以随手记下：
mh_write_skill(
    search_agent_id=search_id,
    name="two_step_decomposition",
    description="把分类强拆两步：先问 '有错吗？' 然后再定罪",
    code_template="""
STEP 1 — 拆解: 有错吗 (yes/no), 波及范围有多大 (high/medium/low)
STEP 2 — 定罪: yes+high → BLOCKER, yes → IMPORTANT...
"""
)
```

今天蒸出来的绝活，就是明天战役的火种。敲一句 `bene mh knowledge`，满载而归。

### 第三杀招 — 群狼环伺，一个中心枢纽

把那只孤狼 proposer 踢走，在这个 benchmark 上直接拉起一个狼群。大家各有各的开局，并且每隔一段时间就在枢纽 (hub) 里碰头换情报：

```bash
# 吹响群狼协同进化的号角 (MCP 或者 Python 都能玩)
mh_spawn_coevolution(benchmark="code_review", n_agents=3)
```

每只狼的生活极其规律：先在自己的小圈子里卷；每卷够 `hub_sync_interval` (默认 2) 轮，就跑去 hub 里碰个头；去扒一扒兄弟们最猛的 harness 和学到的绝活，全揣进自己的档案馆；接着这些泊来品就会堂而皇之地出现在你的帕累托前沿和下一轮的摘要里。

```text
Hub 的巢穴 (VFS):
  /best_per_agent/agent_0/   ← 众狼上贡的极品
  /best_per_agent/agent_1/
  /best_per_agent/agent_2/
  /shared_skills/            ← 大家一起攒出的绝活库
  /shared_attempts/          ← 所有狼的简明阵亡名单
```

在这套 CORAL 战法中，群狼进化的突破频率比独狼直接高出了 **3-10倍**。有 36% 的突破性进展直接踩在了隔壁兄弟的肩膀上 —— 而这种站在巨人肩膀上的变种，有 17% 的概率能再次突破 (相比大盘只有可怜的 9%)。

### 从黑框框里查状态抓技能

```bash
# 去扒一个正在跑的战役卡死了没
bene mh status <search-agent-id>
# → stagnant_iterations: 3, last_pivot_at: iter 7 (连跪了三轮，上次被逼急了转向是在第七轮)

# 端出所有 benchmark 上积攒出来的全套绝活
bene mh knowledge

# 刻进去一条新绝活 (MCP 专武 `mh_write_skill` 也能干)
# MCP 要传这个: { "search_agent_id": "<id>", "name": "two_step", "description": "...", "code_template": "..." }
```

### 一场被扒得连内裤都不剩的实战解析

这是一场只有 15 轮的代码评审大搜捕 (胜率从 48% 一路狂飙到 83%)，它把这三招全玩了一遍：

- 轮次 1-7 — 玩角色扮演和塞 few-shot 的套路，死活卡在 0.74 的烂泥潭里
- 第 7 轮 — `stagnant_iters=4` 阈值引爆了 CORAL 死亡宣判，逼它转向
- 第 8 轮 — 它交出了 "两步强拆法" (two-step decomposition)，一举刺破苍穹 (+0.04)
- 第 10 轮 — 心跳机制启动，把这份功力当场刻写进知识网 agent 里
- 第 10 轮 — two_step_attr_merged 横空出世，以 0.83 的傲人战绩结束战役

**总开销 $0.14，耗时 12 分钟，硬拔了 35 个点的准确率。**

---

## 绝对能传给下一代的遗产 (v0.2.0)

这场战役打完就散？没这回事。那些赢下战争的 harness 会被统统充公，归入一个名叫 "bene-knowledge" 的常驻 agent 麾下。当你在同样的 benchmark 上拉起下一场战役时，这些祖宗留下的心血会被自动调出来，充当额外赠送的开局 seeds。

```bash
bene mh knowledge       # 把所有 benchmark 攒下的绝活全部抖搂出来
bene mh lint <id>       # 给档案馆做个全身体检
bene search "TF-IDF"    # 拿着全文检索引擎，把所有 agent 挖地三尺
bene index <agent-id>   # 给它建一份人类能直接点的 /index.md 导引
```

---

## 随书附赠的考卷 (Benchmarks)

Meta-Harness 论文原版里跑出来的三大考卷，bene 全给你备好了加载器。头一回会从 HuggingFace 往下薅；只要下过了，它就会老老实实蹲在 `~/.cache/bene/datasets/` 里，从此断网也能跑。

| 考卷代号 | 枪栓 (Loader) | 到底是考啥的 | 哪里搞来的 |
|---|---|---|---|
| `lawbench` | `load_lawbench()` | 枯燥的法律文书定性 | HuggingFace |
| `symptom2disease` | `load_symptom2disease()` | 听病情断绝症 | HuggingFace |
| `uspto_50k` | `load_uspto50k()` | 把化学反应分门别类 | HuggingFace |

### 在终端敲出指令

由于论文里的三本神卷 (`lawbench`, `symptom2disease`, `uspto_50k`) 全给锁进了 Python API 里，它们不接客。要在终端体验，请翻牌内置的三本大卷：

```bash
bene mh search -b text_classify -n 20 -k 3
bene mh search -b math_rag -n 20 -k 3
bene mh search -b agentic_coding -n 10 -k 2
```

### 用 Python 接盘

```python
from bene.metaharness.benchmarks.paper_datasets import (
    load_lawbench,
    load_symptom2disease,
    load_uspto50k,
)

# 每抠一下扳机，就会送出一个随时可以扔进 MetaHarnessSearch 的 benchmark 对象
bench = load_lawbench()
# 或者
bench = load_symptom2disease()
# 又或者
bench = load_uspto50k()

search = MetaHarnessSearch(db, router, bench, SearchConfig(
    benchmark="lawbench",
    max_iterations=20,
    candidates_per_iteration=3,
))
result = await search.run()
```

---

## 在 Python 里发号施令

```python
from bene import Bene
from bene.metaharness import SearchConfig
from bene.metaharness.search import MetaHarnessSearch
from bene.metaharness.benchmarks import get_benchmark
from bene.router import TierRouter

db = Bene("search.db")
router = TierRouter.from_config("bene.yaml")

config = SearchConfig(
    benchmark="text_classify",
    max_iterations=20,
    candidates_per_iteration=3,
    objectives=["+accuracy", "-context_cost"], # 既要命又要钱
)

bench = get_benchmark("text_classify", dataset_path="my_data.csv")
search = MetaHarnessSearch(db, router, bench, config)
result = await search.run()

print(result.summary())
for point in result.frontier.points:
    print(f"  {point.harness_id}: {point.scores}")
```

---

## 把所有开关列在同一处

```bash
# 鸣枪开打
bene mh search -b 哪份考卷 -n 跑几轮 -k 每轮憋几个变种
    --proposer-model MODEL    # 强行指定拿谁当 proposer
    --eval-model MODEL        # 强行指定拿谁当判卷官
    --max-parallel N          # 并发爆破
    --eval-subset N           # 切片抽查，图个快
    --dry-run                 # 只准碰开局 seed，摸个底就滚
    --background              # 一把甩给后台 worker

# 把上次死掉的局强行救活，接着跑
bene mh resume 那个死掉的搜索AGENT_ID

# 站在边上吃瓜盯梢
bene mh status 正在跑的搜索AGENT_ID

# 看看帕累托金字塔尖
bene mh frontier 正在跑的搜索AGENT_ID

# 抓某一个跑完的 harness 出来毒打
bene mh inspect 搜索AGENT_ID 指定的HARNESS_ID

# 给档案馆把个脉
bene mh lint 搜索AGENT_ID

# 逛逛那座装满各路绝活的知识库
bene mh knowledge
```

---

## 血脉渊源和实战靶场

- **那篇造神论文:** [Meta-Harness: Optimal LLM Harness Design through Evolutionary Search](https://yoonholee.com/meta-harness/) (arXiv:2603.28052)
- **开山鼻祖的源码:** [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)
- **缔造者们:** Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, Chelsea Finn (集结了 Stanford / KRAFTON / MIT 的众神)

### 可以直接抄的靶场代码

**给工程师准备的硬核靶场:**

- [客服工单分流器](../examples/meta_harness_support_tickets.py) — 把上面扯了半天的实战全撸成了可执行的 Python，连自带的数据集都包好了
- [拿 RAG 搞定数学题](../examples/meta_harness_math.py) — 看看到底什么样的外挂检索，才能喂饱解数学题的模型
- [把 Agent 的代码引擎拉爆](../examples/meta_harness_coding.py) — 死磕一套极致的编程 agent 专属脚手架

**给老板看能赚钱的靶场:**

- [盘一盘客户 LTV 生命周期价值](../examples/meta_harness_clv_prediction.py) — 拿着流失预警，按分层给客户喂不同的 prompt，把 LTV 抠到骨头里
- [群发 CRM 大字报](../examples/meta_harness_crm_campaigns.py) — 语气、CTA 还有客制化文案的千人千面大清洗
- [抓骗子 (反欺诈)](../examples/meta_harness_fraud_detection.py) — 左手红线清单，右手对比样本，把查杀率和命中率直接干满
