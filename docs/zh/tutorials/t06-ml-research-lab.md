# 一夜试遍四种假说：在 BENE 上跑一个通宵的 ML 炼丹实验室

*机器学习研发篇*

把四套截然不同的模型训练思路同时跑起来 —— 就在同一个集群上，仅仅花一个晚上 —— 并且在第二天早晨，用一张冰冷无情的 SQL 数据表，而不是凭你虚无缥缈的直觉，来敲定接下来的研发方向。这篇教程将带你搭一个通宵跑的无人炼丹实验室：四只 agent 将背对背地测试四种完全正交的假说 (LoRA、Lion 优化器、大 Batch 缩放、正则化)，每一只都关在自己绝对隔离的文件系统里，而它们所做的每一个动作，全都被死死咬进同一个随时能拉出来审计的数据库里。

**在你蒙头大睡的这晚，四种假说在暗中疯狂赛跑；等到天亮，只需一条 SQL 查询，就能告诉你昨晚的冠军把 `val_loss` (验证集损失) 生生砸下去了 19.2%。**

在 ML 圈子里，做实验默认都是串行的：拍出一个假说，开跑，死盯着损失曲线看，然后再拍下一个假说。卡脖子的从来不是你想点子的速度，而是这个跑回归的破循环 —— 当你手头攒了四个牛逼的想法时，你已经在悄无声息中搭进去了四个晚上的青春。BENE 给出的解法非常暴力：既然你有四个想法，那就派四只 agent 出去，让它们在同一时间一起跑。

---

*22:00 准时鸣枪起跑；查 Batch 缩放的那只在 00:14 最先交卷，摸架构的那只在 05:47 最后完赛；06:00 准时发出的那条 SQL 查询，当场宣判了冠军归属。*

---

## 今晚的任务：打爆 2.34 的 `val_loss`

我们的基线是一个在莎士比亚全集上跑出来的、字符级别的语言模型，现在的成绩卡在 `val_loss = 2.34`。手头有四个极具潜力的想法，每一个分派给一只专门的 agent：

- **arch-explorer (架构拓荒者)**：拿 LoRA 适配器跟全参微调 (full finetune) 刚正面 —— 它的底气是，对于这种小模型来说，越少的可训练参数反而能带来更强的泛化能力。
- **optim-explorer (优化器拓荒者)**：让 AdamW 和 Lion 在八角笼里死磕 —— 它的底气是，Lion 这种基于符号 (sign-based) 的更新策略，简直就是小语言模型的天菜。
- **scale-explorer (缩放拓荒者)**：把 batch size 32 和 128 拉出来遛遛 —— 它的底气是，喂给它更大的 batch 能够强行稳住字符级训练时抽风的梯度。
- **reg-explorer (正则化拓荒者)**：在 dropout 0.1 和 0.3 之间左右互搏 —— 它的底气是，这么点大的模型绝对已经过拟合了，必须下重手加正则化。

如果你挨个跑，今晚这活得干四个晚上。如果你把它们塞进 BENE 里跑，今晚就搞定。

## Step 1 — 放出四只带沙盒的特种兵

```bash
bene parallel \
  "spawn arch-explorer  --from ./charlm --task lora_vs_full" \
  "spawn optim-explorer --from ./charlm --task adamw_vs_lion" \
  "spawn scale-explorer --from ./charlm --task batch_32_vs_128" \
  "spawn reg-explorer   --from ./charlm --task dropout_01_vs_03"

# [arch-explorer]   成功投放战场  vfs_id=arch-2a1b  status=running
# [optim-explorer]  成功投放战场  vfs_id=opt-5c3d   status=running
# [scale-explorer]  成功投放战场  vfs_id=scl-8e4f   status=running
# [reg-explorer]    成功投放战场  vfs_id=reg-1g7h   status=running
#
# 4 匹战狼正在并发炼丹 — 22:00
```

它们拿到的是四份完全互不相干的 `train.py` 拷贝，四个结界重重的虚拟文件系统，没有任何一丝一毫的共享状态。不需要加锁，不需要 merge 代码：没有任何一只 agent 能把隔壁兄弟辛辛苦苦炼出来的最优 checkpoint 踩掉，并且在未来，任何一炉实验，都能随时从它当年所在的那个 VFS 结界里做到像素级复刻。

## Step 2 — 撒手让 "保留还是回滚" 循环自己跑

在各自的沙盒结界里，每只 agent 都在一丝不苟地重复着同一套铁血纪律：改一个参数，开炼，拿跑出来的分数去碰瓷目前手里的最优解，如果比原来好就保留 (keep)，要是拉胯了就当场回滚 (revert)。看看半空中正在跑的两只 agent：

```text
Agent: arch-explorer (架构拓荒者)
  ├── 读了读 /train.py
  ├── 把配置改成了 CONFIG["activation"] = "swiglu"
  ├── 开炼 → 跑出来的 val_bpb = 1.12 (从 1.18 进步了)
  ├── 保留这次修改 ✓
  ├── 把配置改成了 CONFIG["n_layers"] = 8
  ├── 开炼 → 跑出来的 val_bpb = 1.25 (开倒车了！)
  ├── 回滚这次修改 ✗
  ├── 把配置改成了 CONFIG["pos_encoding"] = "learned"
  ├── 开炼 → 跑出来的 val_bpb = 1.10 (又有进步！)
  ├── 保留这次修改 ✓
  └── ... 继续刚 ...

Agent: optim-explorer (优化器拓荒者，在平行时空同时跑着)
  ├── 读了读 /train.py (它自己兜里的那份，跟 arch-explorer 拿的那份没半毛钱关系)
  ├── 把配置改成了 CONFIG["optimizer"] = "lion"
  ├── 开炼 → 跑出来的 val_bpb = 1.05 (一波巨大的提升！)
  ├── 保留这次修改 ✓
  └── ... 继续刚 ...
```

这两只 agent 都在疯狂往一个叫 `/train.py` 的文件里写东西 —— 没事，因为所有的写入，都只落在了各自专属的 VFS 结界里。所谓的 "并发防撞车"，压根就不需要任何人去写什么代码来处理；因为有了绝对的物理隔离，撞车这种事从根源上就被抹杀了。

漫漫长夜，它们的战报陆续传了回来：

```text
[00:14]  scale-explorer   完赛  最终的 final_val_loss=2.21  (干掉 5.6%)
         探明真相: batch_size=128 确实能稳住训练。收敛速度肉眼可见地变快了。

[01:47]  reg-explorer     完赛  最终的 final_val_loss=2.28  (干掉 2.6%)
         探明真相: dropout=0.3 聊胜于无。杯水车薪。

[03:31]  optim-explorer   完赛  最终的 final_val_loss=2.19  (干掉 6.4%)
         探明真相: 在这活儿上，Lion 优化器完爆 AdamW。字符级的表现好太多了。

[05:47]  arch-explorer    完赛  最终的 final_val_loss=1.89  (干掉 19.2%)
         探明真相: LoRA + 余弦退火 (cosine LR schedule)。毫无争议的最强王者。
```

看交卷的顺序，你就能猜出里面发生了什么。动 batch size 这种事简直就是顺手牵羊，所以 `scale-explorer` 在 00:14 就打卡下班了。而 `arch-explorer` 熬到了 05:47 才收工 —— 因为 LoRA 需要跑很久才能收敛，为了得出严谨的结论，这只 agent 甚至硬生生跑完了两个完整的训练周期。

## Step 3 — 一条 SQL，宣判成败

```sql
SELECT
  agent_name,
  final_val_loss,
  ROUND((2.34 - final_val_loss) / 2.34 * 100, 1) AS improvement_pct,
  train_time_min,
  notes
FROM ml_results
WHERE run_id = 'overnight-2026-04-15'
ORDER BY final_val_loss ASC
```

```text
Agent            val_loss  Improvement  Time    Finding
---------------  --------  -----------  ------  ----------------------------------
arch-explorer    1.89 *    -19.2% *     347min  LoRA + 余弦退火 (cosine LR schedule)
optim-explorer   2.19      -6.4%        191min  Lion 优化器锤爆了 AdamW
scale-explorer   2.21      -5.6%        74min   batch=128 能稳住收敛
reg-explorer     2.28      -2.6%        182min  dropout=0.3 聊胜于无

* 桂冠归属
```

这不仅是赢，这是血洗：`arch-explorer` 靠着 LoRA 和余弦退火的王炸组合，生生把成绩干到了 `val_loss` 1.89，比 2.34 的基线低了令人发指的 19.2%。而 `optim-explorer` 跑出来的那个 Lion (-6.4%)，显然就是下一步往这套最强阵容上继续叠甲的最佳候选人。

## Step 4 — 把冠军的祖传偏方抠出来

登顶的 agent 会把它的心得体会自己写好。直接伸手进它的 VFS 里掏出来看就行了：

```text
bene read arch-explorer /results/best_config.md

## 最强配置战报 — val_loss = 1.89

### 动刀了哪些架构
- LoRA 秩 (rank): 8 (r=8, alpha=16)
- 挂在什么地方: 所有的注意力层里的 q_proj, v_proj
- 拿全参微调跑出来的基线: val_loss=2.34 (死活降不下去)
- 拿 LoRA 跑出来的成绩: val_loss=1.89 (硬生生干下去了 19.2%)

### 炼丹手法的微调
- 学习率调度策略: 带 warmup 的余弦退火 (拿 1% 的步数搞 warmup)
- 峰值学习率 (Peak LR): 3e-4 (本来是 1e-3 — 因为 LoRA 太敏感了，所以压低了)
- 梯度裁剪 (Gradient clip): 1.0 (没动过)

### 假说已被实锤
在对付这种袖珍的字符级模型时，极简的参数微调 (LoRA) 简直把全参微调按在地上摩擦。
极其收敛的参数量，死死摁住了它在莎士比亚语料上疯狂过拟合的毛病。
```

## Step 5 — 把战利品死死锁进金库，当成下一次起飞的弹射板

只需两条指令，昨晚打下的江山，就会化作明晚继续开疆拓土的基石：给冠军拍个快照锁死，然后把 meta-harness (演化脚手架) 搜索引擎的枪口直接架在这上面。

```bash
bene checkpoint arch-explorer --label winning-lora-config

# 用这只 agent 昨晚趟出来的血泪教训，作为下一场搜索的火种
bene mh search \
  -b char_lm \
  --seed-from arch-explorer \
  --model claude-sonnet-4-6 \
  -n 10

# [mh-search] 正在从 arch-explorer 脑子里抽取知识...
# [mh-search] 成功提取神技: lora_param_efficiency (LoRA 参数极简), cosine_lr_warmup (余弦预热)
# [mh-search] 拿最强配置当起跑线: val_loss=1.89
# [mh-search] 本轮搜寻直接从已知的巅峰阵地起飞，不再是从零开始的瞎碰
```

跟进的这轮搜寻，一上来起跳的分数就是 1.89，而不是那个惨不忍睹的 2.34，并且会把关于 LoRA 的心得像随身老爷爷一样当成可复用技能 (reusable skill) 带着走。这样连续熬过三个晚上，知识库 agent (knowledge agent) 肚子里就会囤满针对这套架构的打法大全 —— 等到第 4 晚开跑时，它开局拿到的那手好牌，如果换作人肉去试，起码得搭进去几周的时间。所有的赢面都在雪球般地复利叠加，而不是每次都被清零。

## 天亮后查账

除了那份排好座次的榜单外，事件流水账 (event journal) 还能回答一堆结果文件里死活找不出的运营问题 —— 比如，每只 agent 到底干了多少活，这晚总共烧了多少算力，以及究竟有哪些文件真被动过手脚：

```sql
-- 问: 每只 agent 到底跑了几把实验？
SELECT a.name, COUNT(tc.call_id) AS experiments
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
WHERE tc.tool_name = 'shell_exec'
GROUP BY a.agent_id;

-- 问: 这群牲口这晚总共吃了多少算力？
SELECT SUM(token_count) AS total_tokens,
       SUM(duration_ms) / 1000.0 AS total_seconds
FROM tool_calls;

-- 问: 谁名下的 train.py 被改得面目全非？
SELECT a.name, f.version AS modifications
FROM files f JOIN agents a ON f.agent_id = a.agent_id
WHERE f.path = '/train.py'
ORDER BY f.version DESC;

-- 问: 那个跑第一的家伙，最后到底往 train.py 里塞了什么狗屁代码？ (直接把它的那份代码拔出来看)
SELECT content FROM files f
JOIN agents a ON f.agent_id = a.agent_id
WHERE a.name = 'arch-explorer' AND f.path = '/train.py';
```

这一切的一切，都在用同一种 SQL，死死咬着同一个 `.db` 文件。

## 更喜欢用 Python？CLI 底下藏着的原生 SDK 满足你

`bene parallel` 说白了也就是用 Python SDK 糊出来的一层薄薄的外皮。当你需要给每只 agent 发放独家开局剧本、精雕细琢特定的推演指令、或者等它们全跑完后还要做一波 map-reduce 操作时，你可以直接写 Python 脚本来盘它们。

**把炼丹祖传代码备好。** 每只 agent 都会领到这份代码的一份绝密拷贝。

```python
BASE_TRAIN_PY = """
CONFIG = {
    "n_layers": 6,
    "n_heads": 6,
    "d_model": 384,
    "learning_rate": 3e-4,
    "optimizer": "adamw",
    "activation": "gelu",
    "dropout": 0.1,
}

def train(config):
    # ... 你祖传的 PyTorch 炼丹炉循环 ...
    return {"val_bpb": val_loss}
"""
```

**划定拓荒方向。** 给每只 agent 一道死命令；给出去的 prompt 就是它们的行动纲领。

```python
DIRECTIONS = [
    {
        "name": "arch-explorer",
        "prompt": "去趟一趟架构方面的水：拿 LoRA 去跟全参微调碰一碰，试试动动层数、"
                  "注意力头、或者是激活函数。一次只能改一样。遇到好成绩就留下。",
    },
    {
        "name": "optim-explorer",
        "prompt": "去趟一趟优化器的水：拿 AdamW 去跟 Lion 刚正面，试试捣鼓一下学习率、"
                  "权重衰减系数 (weight decay)、或者是 warmup 策略。遇到好成绩就留下。",
    },
    {
        "name": "scale-explorer",
        "prompt": "去趟一趟缩放比例的水：把 batch size 的 32 和 128 拉出来遛遛，试试调一下 FFN 比例、"
                  "或者是头数 (head count) 跟头的维度 (head dim) 的博弈。把最稳的那套配置找出来。",
    },
    {
        "name": "reg-explorer",
        "prompt": "去趟一趟正则化的水：搓一搓 dropout 率，调调 weight decay，以及看看跟 batch-size 之间"
                  "有没有什么化学反应。遇到好成绩就留下。",
    },
]
```

**空投，拍照，开跑。**

```python
from bene import Bene
from bene.ccr import ClaudeCodeRunner
from bene.router import TierRouter

db = Bene("research-lab.db")
router = TierRouter.from_config("bene.yaml")
ccr = ClaudeCodeRunner(db, router, checkpoint_interval=5)

for direction in DIRECTIONS:
    agent_id = db.spawn(direction["name"])
    db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent_id, label="baseline")

results = await ccr.run_parallel(DIRECTIONS)
```

`checkpoint_interval=5` 这个参数，会让它每熬过 5 轮就默默存个盘。哪怕在第 23 轮炸机了，你最多也就搭进去 3 把实验的心血：一键倒回到第 20 轮的存盘点，拍拍灰接着跑。系统就算崩溃，今晚这炉丹也绝不会付之东流。

## 玩笔大的：三张显卡，六只特种兵，高低模型混合编队

当这个实验室的胃口大到一张 GPU 塞不下的时候，tier router (层级路由) 会直接接管，用 `force_model` 强行把特种兵派发到特定的模型池里去：那种纯靠人海战术的穷举调参，统统丢给便宜的小模型；而那些需要脑洞大开去凭空捏造全新假说的活，全部分配给拥有满级算力的大模型。

### 布阵图

```text
GPU 0 — Qwen2.5-Coder-7B    (端口 8000) → 2 只穷举兵 (负责闭着眼睛狂扫超参数)
GPU 1 — Qwen2.5-Coder-32B   (端口 8001) → 2 只架构师 (负责探索各种骚气的设计)
GPU 2 — DeepSeek-R1-70B      (端口 8002) → 2 只科研大佬 (负责憋出前所未见的神级假说)
```

### 挂参数

```yaml
# bene.yaml
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, sweep]
  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for: [moderate, architecture]
  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for: [complex, novel_research]
```

### 一声令下，六狼齐出

```python
# examples/multi_gpu_research.py
from bene import Bene
from bene.ccr import ClaudeCodeRunner
from bene.router import TierRouter

db = Bene("multi-gpu-research.db")
router = TierRouter.from_config("bene.yaml")
ccr = ClaudeCodeRunner(db, router, checkpoint_interval=5)

DIRECTIONS = [
    # GPU 0 — 7B: 穷举疯狗
    {"name": "lr-sweep",    "prompt": "把学习率从 1e-5 到 1e-2 统统扫一遍",
     "config": {"force_model": "qwen2.5-coder-7b"}},
    {"name": "batch-sweep", "prompt": "把 batch sizes 从 16 到 256 统统扫一遍",
     "config": {"force_model": "qwen2.5-coder-7b"}},

    # GPU 1 — 32B: 架构猎场
    {"name": "arch-depth",  "prompt": "去探探更深层的架构 (12-24 层深)",
     "config": {"force_model": "qwen2.5-coder-32b"}},
    {"name": "arch-width",  "prompt": "去探探更宽泛的架构 (512-2048 的 d_model)",
     "config": {"force_model": "qwen2.5-coder-32b"}},

    # GPU 2 — 70B: 科研核弹区
    {"name": "novel-loss",  "prompt": "设计一个前所未见的、把对比学习 (contrastive) 和生成式 (generative) 缝合在一起的怪胎损失函数",
     "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "novel-arch",  "prompt": "想个绝活，捏一个专门用来对付超长上下文的诡异注意力机制出来",
     "config": {"force_model": "deepseek-r1-70b"}},
]

for d in DIRECTIONS:
    agent_id = db.spawn(d["name"])
    db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent_id, label="baseline")

results = await ccr.run_parallel(DIRECTIONS)
```

在 GPU 0 上疯跑的 7B 就像清道夫一样把调参的脏活一扫而空；而镇守在 GPU 2 的 70B 虽然推演得慢，但它一旦开口，吐出来的绝对是那种脑洞大开的神仙路数。没有谁会等谁，没有任何一只 agent 被别人拖累，这六只狼全都在物理隔离的结界里狂奔，并且最后，它们所有的战利品都会被整整齐齐地塞进同一个 `.db` 里，乖乖等着你用同一口 SQL 去盘它们。

## 算总账：这晚到底值不值

```text
姿势                       挂钟耗时  榨干工程师的时间             趟过多少假说
-------------------------  ---------  --------------------------  -----------------
全靠人肉 (串行排队跑)      4 晚       4 遍苦逼的配置 + 漫长的分析   4
BENE 兵分四路夜袭          1 晚       睡前搭 30 分钟 + 睡醒看 15 分钟   4
```

趟过的假说数量一模一样；但在日历上划掉的日子却有着天壤之别。在这个流派里，要你亲自上手的地方被残暴地压缩到了睡前花半小时搭场地，外加醒来后花一刻钟念战报。而且，这四条路哪怕跑崩了三条，也绝对不算白跑 —— 那些跑废掉的尸体，依然是能喂饱下一场战役的、带着血肉的极品饲料。

## 这种邪道打法是从哪抄来的

这个破实验室，说白了就是把 [Karpathy 的 autoresearch](https://github.com/karpathy/autoresearch) 给开了分身外挂。在 autoresearch 的套路里，是一只孤狼 agent 守着一张显卡和一份训练代码：改一下 `train.py`，跑一把，盯一会曲线，把提分的招数咽下去，把拉胯的动作吐出来，然后死循环一整晚。它的横空出世证明了这样一个极其狂妄的事实：所谓高大上的科研闭环，其实早就沦为了一种纯粹的体力活，完全可以直接外包给大模型 —— 因为模型它真的能看懂损失曲线，并且还能凭直觉猜出下一步该怎么走。而在 autoresearch 里唯一没被颠覆的，是这个闭环本身依然是单线程串行的。

BENE 则一脚踹开了这个枷锁，直接把这套闭环无限分身：拉起 N 匹狼，给每匹狼在私有 VFS 里发一份训练代码拷贝，然后把它们同时踹向 N 条互不相交的死胡同去试错，且谁也别想动谁的奶酪。等天一亮，所有的战利品统统只用一条查询就能收缴完毕，而每匹狼在夜里用命趟出来的教训，都会通过 BENE 的知识库 agent，化作下一场战役的火种。

### 摆在一起看

| autoresearch 原版 | BENE 炼丹实验室 |
|---|---|
| 单狼，单卡 | N 狼齐出，N 条战线，纯并发 |
| 靠 Git 的 commit/reset 来实现土制存档 | 拥有带精确 diff 记录的工业级快照系统 |
| 拿个 `results.tsv` 的破文件记流水账 | 基于 SQLite、全量支持 SQL 拷问的事件流水系统 |
| 拿 Git log 来充当半残的审计流水 | 拥有 14 种事件类型的、强制只能追加的纯血审计记录 |
| 只有一份 `train.py`，只能在原处动刀子 | 每一只狼都分到了一份被关在隔离区里的专属文件复刻本 |
| 苦逼地人肉翻阅战果 | `bene query "SELECT ..."` 一键全知全能 |
| 一次只能摸着石头过一条河 | 架构探索、优化器海选、缩放调参、正则化试探，四条河同时过 |

这些差别的背后，是你真金白银省下来的血汗：

- **零配置，原生隔离。** autoresearch 是硬生生在那份 `train.py` 上动土的，所以你要想让它同时探几条路，就得苦逼地去折腾 git worktrees 或者自己人肉拷贝好几份文件夹。而在 BENE 里，任何 agent 被放出来的那一刻，系统就会免费发给它一个私有的虚拟文件系统 (VFS)。
- **正经快照，不用 Git 邪术。** autoresearch 只能极其卑微地依赖 `git commit` 和 `git reset`。而在 BENE 里，一次快照就能把文件、运行状态、事件水位线等全盘定格，不仅能与其他快照极其干净地进行 diff，更牛逼的是，它能将某一只闯祸的 agent 单独时光倒流，而对隔壁那些还在埋头苦干的兄弟们不会造成任何干扰。
- **拿 SQL 拷问真相。** 谁跑出了最低的损失率？今晚到底总共烧了多少炉实验？那只炸机的 agent 到底在哪一步踩了坑？所有的这些，全是对着流水账去敲一条 SQL 查询的事，而不是去那个破 TSV 文件里写一大串正则表达式。
- **这个实验室，你可以装在口袋里带走。** 特种兵、战利品、战报流水：统统塞在这一个 `.db` 文件里。发给同事、装在另一台机器上跑、或者是拿 `cp` 备份，随你便。
- **碾压级的吞吐量。** autoresearch 在单卡上，一小时大概能搓出 12 炉丹。如果换作 4 匹 BENE 战狼驾驭 4 张卡，一小时就能交出 48 炉 —— 每一炉都摸向了截然不同的深海，且每一炉的数据都被打上了清晰的钢印。

---

这就是这场通宵炼丹局的全部真相。你在 22:00 丢下了四个异想天开的赌注，在 06:00 准时来收尸：最强的那套配置已被死死冻结进快照里，登顶的霸主早已自己写好了战报总结，而它趟出来的独门秘籍也已经被打包成了神技 (skills)，等着下一场搜索战役将它作为起手式。实验室自己就把活干完了；你唯一要干的，就是在开局抛出赌局，并在剧终时宣判成败。

## 顺藤摸瓜

- [README 首页](../README.md) — BENE 全景大局观和全套文档入口
- [破局战法 (Use Cases)](../use-cases.md) — 更多来自泥坑一线的实战套路
- [破局战法：无人科研炼丹实验室](../use-cases.md#autonomous-research-lab)
- [核心部件指南：跨代技能库 (Skills)](../skills.md)
- [Karpathy 搞出的 autoresearch](https://github.com/karpathy/autoresearch) — 单兵作战流派的祖师爷
- 拿去就能跑的真家伙:
  - [`examples/autonomous_research_lab.py`](../../examples/autonomous_research_lab.py) — 1 张卡，4 匹狼的低配场
  - [`examples/multi_gpu_research.py`](../../examples/multi_gpu_research.py) — 3 张卡，6 匹狼的诸神之战
- [教程 t11 — 驾驭本地 vLLM 狼群](./t11-local-agents-vllm.md) — 手把手教你在本地搭 vLLM + BENE

---

*BENE 基于 MIT 协议开源，并且它所吹嘘的 "数据绝对不出境" 是经得起查水表的：这篇教程里出现过的所有 agent、实验过程以及产出的结果，自始至终都被死死封印在你本地硬盘的那个 SQLite 文件里 —— 没有任何一个字节流向云端，所谓全量备份，也不过就是一句 `cp` 文件的基本操作。*

*那套单兵作战的路数，最早是 [Karpathy 在 autoresearch 里趟出来的](https://github.com/karpathy/autoresearch)；而 BENE 则是硬生生把它裂变出了 N 个并发的平行宇宙，给每一个宇宙发了一个绝对隔离的 VFS 结界，外加一套能用 SQL 拷问一切真相的流水账系统，以及跨越世代、永远不会遗忘的传承知识库。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
