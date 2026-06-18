# BENE 十分钟速通：端到端实战演练

*放出去一个 agent。盯着它干活。扒光它的作案记录。一旦搞砸直接回滚。最后把整场战役打包成一个单独的 `.db` 文件甩给你的队友。*

这篇教程是你的**新手村入口**。它会带你走马观花地把实战 triage (急诊排障) 和 SDLC (软件开发生命周期) 里最常用的 BENE 核心部件全摸一遍 —— 虚拟文件系统 (VFS)、快照回滚 (Checkpoints)、审计流水线 (Audit trail)、控制台仪表盘 (Dashboard) 以及演化脚手架 (Meta-harness) —— 不会讲太深。每个部件都会指向各自的硬核长文，方便你吃透底层。

![BENE — 绝对隔离的沙盒、坚不可摧的执行流水、可复用的认知沉淀](../assets/hero-v04.png)

---

## 战前准备

| 你需要啥 | 怎么搞到手 |
|---|---|
| 装好的 BENE | `git clone https://github.com/good-night-oppie/bene.git && cd bene && uv sync` |
| 能用的大模型 | 下面任选其一：Anthropic API 密钥，OpenAI API 密钥，本地跑的 vLLM，或者带了 Claude Code 订阅。`bene setup` 会手把手帮你选。 |
| 大概 10 分钟 | 顺便泡杯咖啡。 |

---

## Step 1 — 徒手起个项目 (耗时 30秒)

```bash
bene setup        # 傻瓜向导：帮你选模型、写 bene.yaml、顺手建好 bene.db
bene demo         # 选做：在库里强行塞一点极其逼真的模拟战役数据
bene ui           # 砸开浏览器看仪表盘
```

这个控制台仪表盘就是你监工 agent 干活的地方。去翻翻 [Dashboard 控制台](../dashboard.md) 来了解那张 Gantt 甘特图、探视镜以及活蹦乱跳的事件信息流。

---

## Step 2 — 放出去第一只 Agent (耗时 1分钟)

```bash
bene run "滚去把 src/payments.py 里的 SQL 注入漏洞给我找出来" --name security-review
```

在敲下回车的这一秒，系统里到底发生了什么：

1. BENE 在 `agents` 表里夯进去了一条状态为 `running` (正在跑) 的记录。
2. 当场切分出一块极其私密的虚拟文件系统 (VFS)，并且死死绑定在这个 agent 的 `agent_id` 上。
3. 这只 agent 在 `bene.db` 里拥有了一套它自己的独立文件系统 —— 它绝对看不见隔壁兄弟的文件。
4. 每读一个文件、每调一个工具、脑子里每闪过一个念头，都会被生生砸进 `events` 审计流水表里，且绝对无法篡改。

现场盯梢：

```bash
bene ls                          # 点名，看生老病死
bene status <agent-id>           # 把这只 agent 扒光细看
bene logs <agent-id> --tail 20   # 只瞄最后 20 条事记
```

底层的隔离魔法和暗网机制全写在 [架构设计 (Architecture)](../architecture.md) 里。想看全套的数据库表结构，去翻 [数据血肉解剖图 (Schema)](../schema.md)。

---

## Step 3 — 动手前先拍个快照锁死 (耗时 10秒)

在这里，打快照跟喝水一样便宜，因为底层的 blob 存储是根据内容寻址的 (content-addressed)；一模一样的文件，在底层只对应一坨带了 SHA-256 钥匙的肉。

```bash
bene checkpoint <agent-id> --label "before-fix"
```

打快照 (Checkpoint)、读档 (Restore) 和比对 (Diff) 是 BENE 用来实施**无情物理隔离**的终极武器 —— 详见 [时空快照 (Checkpoints)](../checkpoints.md) 里教的怎么锁死状态、怎么做外科手术式回滚以及怎么扒开看差异。

---

## Step 4 — 拿并发去趟雷区 (耗时 2分钟)

一句话，同时放出去三只 agent。因为每只狗都拴在自己的 VFS 结界里，所以它们绝对不可能互相踩脚。

```bash
bene parallel \
  -t impl   "重构 src/payments.py，统统给我换成参数化查询" \
  -t tests  "去写几条 pytest 单元测试，死磕参数化查询" \
  -t docs   "滚去把 API.md 里的查询接口描述给更新了"
```

此时的仪表盘里会拉出三条极其舒坦的平行甘特图。等它们全跑完，你就可以直接上 SQL 跨越三只 agent 进行战果审计了 —— 把所有 agent 关进同一个数据库里，图的就是这个：

```bash
bene query "SELECT a.name, COUNT(tc.call_id) AS calls, SUM(tc.token_count) AS tokens
            FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
            GROUP BY a.agent_id"
```

全套的骚操作战术板都在 [破局战法 (Use Cases)](../use-cases.md) 里。如果你想体验真正 AI 式的现场编程工作流，去翻 [植入 MCP (MCP Integration)](../mcp-integration.md)。

---

## Step 5 — 刨根问底式审计 (耗时 1分钟)

一条 SQL，就能扒光整个决策的时间线：

```bash
bene query "SELECT timestamp, event_type, payload
            FROM events
            WHERE agent_id = '<agent-id>'
            ORDER BY timestamp"
```

这小子的 `events` 表是**只能追加 (append-only)** 的。没有任何东西能被原地篡改。在 BENE 看来，这就是传说中的 *基于踪迹的外挂检索 (trace-based RAG)*：下一只接盘的 agent 可以直接把这条执行流水当成第一手资料来啃。去 [跨代记忆库 (Memory)](../memory.md) 和 [经验技能库 (Skills)](../skills.md) 看看这套搜捕打捞机制是怎么运转的。

---

## Step 6 — 一键时光倒流 (毫秒级)

```bash
bene restore <agent-id> --checkpoint <checkpoint-id>
```

回滚是一次纯粹的 SQL 暴击 —— 它直接改写这个 agent 的文件指针和状态记录，强行指回打快照时定格的那坨肉。同一个项目里其他吃瓜的 agent 连毛都不会掉一根。这就是写在 [设计哲学 (Philosophy)](../philosophy.md) 里的最高教条：*物理隔离是不容妥协的铁律 (containment is non-negotiable)*。

如果你想在回滚前先看看到底改了啥：

```bash
bene diff <agent-id> --from <cp-A> --to <cp-B>
```

---

## Step 7 — 用公投来锁死高危操作 (选做)

碰上那些动辄要命的操作 —— 大规模删库、强行回滚、生产环境的发车 —— 用共享日志 (shared log) 把它们锁死，必须拿到明面上的赞成票才能落锤：

```python
from bene.shared_log import SharedLog
log = SharedLog(bene.conn)

intent_id = log.intent("agent-A", "Delete checkpoints older than 7 days")
log.vote("agent-B", intent_id, approve=True, reason="Matches retention policy")
log.vote("agent-C", intent_id, approve=True, reason="Confirmed safe")
decision = log.decide(intent_id, agent_id="agent-A")
if decision.payload["passed"]:
    log.commit("agent-A", intent_id, summary="Removed 47 checkpoints")
```

全套的 LogAct 起意 / 投票 / 决议 / 落锤协议，去 [共享日志总线 (Shared Log)](../shared-log.md) 里翻。

---

## Step 8 — 把祖宗的套路当传家宝 (耗时 2分钟)

如果连着几只 agent 都在同样的地方栽了跟头又爬了起来，你肯定能看出套路。把这套路打包成一个 *skill (技能)*，后面的 agent 就能直接抄作业：

```bash
bene skills save \
  --name parameterize_sql_query \
  --description "把拼字符串的裸奔 SQL 洗成参数化查询；但死守 WHERE 条件的祖传逻辑" \
  --template "去 {file} 里扒出那些拼字符串的 SQL。全换成 {db_driver} 的参数化写法。外加几条对付 {edge_cases} 边缘分支的测试用例。" \
  --tags security,refactor,sql
```

从今往后，不管是在哪跑的 agent，只要一搜就能拿去用：

```bash
bene skills search "sql injection" --order success_count
```

技能 (Skills) 其实就是程序化 (procedural) 的记忆。去翻 [经验技能库 (Skills)](../skills.md)，以及去看看 [群狼协同进化 (Multi-Agent Co-Evolution)](../use-cases.md#multi-agent-co-evolution-coral) 这节，见识下演化脚手架是怎么全自动无情开挂摸出这些套路的。

---

## Step 9 — 连锅端走 (耗时 30秒)

整个 `.db` 文件就是一个极度便携的骨灰盒。你可以随手发给你的队友、挂在复盘工单的附件里、或者直接塞进 S3 当作冷冻琥珀。

```bash
bene export <agent-id> -o agent-snapshot.db   # 连根拔起其中一只 agent
cp bene.db full-engagement-$(date +%Y%m%d).db # 整场战役，连皮带骨全端走
```

拖进 DBeaver，敲进 `sqlite3` 命令行，或者任何能开 SQLite 的工具里。每一个文件、每一次调包、每一条苟延残喘的挣扎，全部原形毕露，统统可以用 SQL 拷问。

---

## 接下来去哪

| 想干嘛 | 去看这篇 |
|---|---|
| 搞懂 BENE 为什么要长这副反骨的模样 | [设计哲学 (Philosophy)](../philosophy.md) |
| 把 BENE 变成一把 MCP 专武，焊死在 Claude Code 或是 Cursor 肚子里 | [植入 MCP (MCP Integration)](../mcp-integration.md) |
| 让上面的这套 `.db` 体系，跑在你自己局域网里的全本地断网大模型上 | [教程 t11 — 驾驭本地 vLLM 狼群](t11-local-agents-vllm.md) |
| 拉起 N 只带着不同假说的 agent 并行死磕，最后拿 SQL 宣判胜负 | [教程 t06 — ML 炼丹实验室](t06-ml-research-lab.md) |
| 遇上硬骨头，靠全自动的演化算法去变异出神级 prompt | [演化脚手架 (Meta-Harness)](../meta-harness.md) 以及 [教程 t01](t01-bene-meta-harness.md) |
| 想看看 Oppie 团队在生产环境里端到端的血泪实盘 | [教程 t02 — 端到端的自我疗愈](t02-e2e-self-healing.md) |
| 想查某一条终端指令 | [命令行兵器谱 (CLI Reference)](../cli-reference.md) |
| 想查某一张表里的某一个字段 | [数据血肉解剖图 (Schema)](../schema.md) |
| 想把 BENE 当成生产集群跑起来 | [出征部署指南 (Deployment)](../deployment.md) |

---

## 你刚刚到底白嫖了些什么

| BENE 核心部件 | 对应上面哪一步 | 想深挖去哪看 |
|---|---|---|
| 虚拟文件系统 (VFS) | Step 2, 4 | [架构设计 (Architecture)](../architecture.md) |
| 时空快照 (Checkpoints) | Step 3, 6 | [时空快照 (Checkpoints)](../checkpoints.md) |
| 审计流水 (Event journal) | Step 5 | [解剖图 → events 表](../schema.md#events) |
| 狼群物理隔离 | Step 4, 6 | [设计哲学 → 隔离是铁律](../philosophy.md#containment-is-non-negotiable) |
| 共享总线 + 投票 | Step 7 | [共享日志总线 (Shared Log)](../shared-log.md) |
| 经验技能库 | Step 8 | [经验技能库 (Skills)](../skills.md) |
| 连锅端走 | Step 9 | [命令行兵器谱 → export 指令](../cli-reference.md) |

如果你老老实实地走完了上面的每一步，恭喜你：你刚刚已经握住并在手里把玩了一遍 Oppie 工程师们在处理线上急诊 (live triage)、夺命连环 call (on-call) 以及搞自愈修复时手边攥着的原版兵器。
