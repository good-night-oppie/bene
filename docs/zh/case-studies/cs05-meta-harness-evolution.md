# 配种计划：在击杀闸门后面进化一套 Harness (The Breeding Program: Evolving a Harness Behind a Kill-Gate)

*Engineering · 2026-06*

---

## 背景 (Context)

Harness —— 也就是包在模型外面的那层控制流程序：它怎么规划、何时重试、检索什么、又如何给自己设闸 —— 通常都是人肉手调出来的。某个人改改 prompt，跑几道任务，觉得"手感更好了"，就这么上线了。这套循环天生带着两个死穴：knob（旋钮）一多就玩不转了，再就是它凭手感晋升 —— 上线的是一套在 demo 里看着不错的策略，而非一套被证明确实干翻了在任者（incumbent）的策略。

这篇案例讲的是 BENE 给出的另一条路：在 benchmark 上跨世代**配种**出更强的 harness 策略，且只有当某个候选者闯过一道留出（held-out）的击杀闸门（kill gate）时才让它晋升。这就是把贝尼·杰瑟里特的配种计划做成了一套工程循环 —— 耐心、跨越多个世代的筛选，绝不让任何候选者靠卖相往上爬。

## 问题拆解 (Problem framing)

想让 harness 自动调优，路上埋着三个坑：

- **过拟合的搜索。** 拿你用来打分的同一批任务去调优，你养出来的就是一套把 benchmark 背得滚瓜烂熟的策略，而不是一套真能泛化的策略。
- **凭自报家门晋升。** 如果一个候选者跑自己那一局就能决定它能不能上线，你拿到的就是自我认证式的"进步" —— 而这恰恰是 eval-probe（评测探针）存在的全部意义：把它堵死。
- **单一数字的隧道视野。** 把"更好"塌缩成一个分数，会把那些真正要紧的取舍（准确率 vs 成本 vs 延迟）全藏起来。

## 设计 (Design)

### 跨世代的反思式变异 (Reflective mutation across generations)

搜索靠**反思式变异**来提出 harness 变种 —— 这是一套 GEPA 风格的循环：它读懂哪里翻了车，再改写策略，一代接一代地推进，而不是瞎撞的随机搜索。每个候选者都是档案馆里一份真实、能跑的 harness 程序。

```bash
bene mh search --benchmark agentic_coding -n 20 -k 4   # 20 generations, 4 candidates each
bene mh status                                          # how the run is progressing
```

### 要的是帕累托前沿，而非唯一赢家 (A Pareto frontier, not a single winner)

候选者按多个目标打分，并以一条前沿的形式保留下来，这样各种取舍始终摆在明面上，不会被平均一刀抹平：

```bash
bene mh frontier                 # the non-dominated set
bene mh inspect <harness-id>     # one candidate: source, scores, trace summary
```

### 晋升躲在留出的击杀闸门后面 (Promotion behind a held-out kill-gate)

这是整套设计里最吃重的一个决策。只有当一个候选者在它从未拿来训练过的**留出**切片上闯过探针时，它才会被自动晋升 —— 用的是和 BENE 里每一条主张都要面对的那道可证伪、哈希锁定（hash-locked）的击杀闸门一模一样的标准。在任者已经能过的闸门没资格当裁判；一个只在训练任务上赢了的候选者永远别想上线。

> 晋升闸门就是配种计划的选择压力。把它放水，你养出的就是 benchmark 背诵机；把它守严，你养出的才是泛化能手。

### 习得的本事会沉淀下来 (Discoveries persist)

搜索学到的东西 —— 哪些变异往往管用、哪些是死胡同 —— 会留存在一个常驻的知识库里，这样后续的搜索是站在攒下来的经验上起步，而不是每次都从零开始：

```bash
bene mh knowledge                # discoveries carried across searches
```

## 洞察 (Insights)

- **搜索和打分绝不能共用任务。** 留出评测，就是养出泛化能手和养出一坨过拟合之间的那道分水岭。
- **晋升是一道闸门，不是一场投票。** 把"往上走"这件事绑死在一道候选者本可能没过的击杀闸门上，正是自动化进化能让人信得过的原因 —— BENE 其余部分一直恪守的同一条规矩，如今也用在了 BENE 自家的策略上。
- **守住前沿。** 多目标筛选把单一分数会抹掉的那些取舍原样保了下来，于是你是睁着眼睛挑策略的。

## 你该从这里带走什么 (What to take from this)

如果你还在手调 prompt、凭手感上线，那你做的是没有选择压力的"选择"。把你的策略扔进档案馆，拿它们去 benchmark 上进化，再把晋升卡死在一道有可能直接干掉候选者的留出探针上。这就是配种计划 —— 一套没法偷偷作弊的自动化改进，因为它和其余一切一样，要对同一道闸门负责。
