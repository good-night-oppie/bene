# 另忆（Other Memory）：基于 trace 的 RAG，让下一个 agent 永不冷启动

*Engineering · 2026-06*

---

## 背景 (Context)

一个 agent 干的最烧钱的事，就是把上一个 agent 早就摸清的东西重新趟一遍。新会话一开，上下文窗口是空的；上一班人学到的所有教训——哪个测试时灵时不灵、哪次重构搞砸了、哪个闸门以什么理由毙了哪个候选——全都没了，除非有人把它写成下一个 agent 真能检索到的形态。

把整段历史一股脑塞回上下文不是答案：贵、撑爆窗口，还会把唯一有用的那条事实埋进成千上万条无关信息里。这篇 case study 讲的是 BENE 默认就给你上的另一条路——**基于 trace 的检索（trace-based retrieval）**，也就是 Bene Gesserit 那套 *另忆（Other Memory）* 背后的工程实现：把每一位圣母的祖传记忆，做成可查询的。

## 问题拆解 (Problem framing)

你想让下一个 agent 继承的是 *已经走过的那条路*，不是整张地图。这就要求底座必须提供三样东西：

- **零仪式感地捕获。** 如果"记下来"得专门走一步显式写入，agent 一定会偷懒跳过。记忆必须是运行本身的副产品。
- **只检索相关的那一片。** 给一个问题，返回那寥寥几条真正相关的 trace——而不是一整份逐字记录。
- **规模上去了也得便宜。** 几千次运行，不能意味着一次线性扫库，也不能意味着把上下文窗口整个倒出来。

## 设计 (Design)

### 捕获是默认行为，不是额外一步

每次运行都会自动落一条 tier-0 的 trace 记忆轨迹（engram）。agent 不需要"决定要不要记住"；harness 边走边把这条路记下来。最小单位是一颗 *granule（粒子）*——一条紧凑的记录，对应一个 turn、一次工具调用、一个结果。

### 一架压缩阶梯，而非一个扁平库

记忆轨迹（engram）活在一架分层的阶梯上（0–4 级）：底层是原始 trace，越往上是逐级压缩的摘要。便宜的高层先查；命中之后，只有当它对得起这份成本时，才往下钻到详细的那一层。当你想精确查询阶梯里的某一片时，可以这样写：

```bash
bene retrieve "why did the regression gate reject candidate 7" --tiers 0,2,3 --k 5
```

### 会做路由的检索，不只是做匹配

检索会挑一个路由器：开启时走一个带熵感知的 **MemGAS** 路由器，否则退回一个自适应兜底方案。关键在于返回那些 *有信息量* 的 trace——真正能降低下一个 agent 不确定性的那几条——而不是字面上最接近的那几条。

```bash
bene retrieve "common failure modes on auth refactors" --memgas
bene retrieve "common failure modes on auth refactors" --adaptive   # 强制走兜底
```

### 按 agent 划界，可追责到具体提问者

一次查询可以归属到发起提问的那个 agent，于是检索遵守的是和 VFS 一样的隔离——记忆在整个系统里持续滚雪球，却不会让某个 agent 的私有工作区泄漏进别人的答案里：

```bash
bene retrieve "what broke last time we touched the parser" --agent refactor-bot
```

## 心得 (Insights)

- **记忆必须免费，才会有人用。** 把捕获做成运行的副产品——而不是 agent 必须时刻记着的自律——这才是让整个语料库完整到值得检索的前提。
- **要压缩，不要堆积。** 把每个 turn 平铺成一条流水日志，规模一大就根本搜不动；一架带下钻能力的摘要阶梯，能让检索在语料库膨胀时依旧便宜。
- **继承胜过重新推导。** 真正可量化的收益不是"agent 拿到了更多上下文"——而是"agent 直接跳过了上一个人早已标记好的死胡同"。走过的那条路，本身就是资产。

## 一句话带走 (What to take from this)

如果你的 agent 每次开会话都从零起步，那你就是在为每一次运行缴"重新发现税"。把 trace 捕获做成底座的默认行为，在检索底下垫一架压缩阶梯，让下一个 agent 直接查这条路，而不是把它重走一遍。这就是另忆（Other Memory）——一个 `bene retrieve` 就到手了。
