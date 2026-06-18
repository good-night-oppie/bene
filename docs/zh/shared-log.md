# 共享日志总线 (Shared Log)

在任何 agent 动手之前，先把决议拿出来公投。shared log 允许 bene 的 agents 在采取行动前拉起提案、投票表决并最终拍板执行或流产 —— 而这一切的共识过程，全被当成日志行硬生生砸进 `bene.db` 里。没有额外的协调进程，没有消息队列 Broker，也绝不走网络。

> **先共识，后动手 —— 而且共识过程的每一步，全是你能直接查底细的数据库行。**

这套协议的内核就是 LogAct，源自 2026 年 Meta 的一篇论文，具体致谢见底部的 [血脉渊源 (Lineage)](#lineage)。

---

## 攒起你的第一场公投

三个 agent，一项动议，一局因为分歧而正确触发动机流产的投票：

```python
from bene import Bene
from bene.shared_log import SharedLog

bene = Bene("project.db")
log  = SharedLog(bene.conn)

# 阶段 1: Agent A 昭告天下它想干嘛
intent_id = log.intent(
    agent_id="agent-A",
    action="Delete all checkpoints older than 7 days",
)

# 阶段 2: 同僚们举手
log.vote("agent-B", intent_id, approve=True,  reason="Matches retention policy.")
log.vote("agent-C", intent_id, approve=False, reason="Need to verify first.")

# 阶段 3: 开票并下达决议
summary  = log.tally(intent_id)   # VoteSummary(intent_id=1, approve=1, reject=1, abstain=0, votes=[...]) (passed 是个 @property)
decision = log.decide(intent_id, agent_id="agent-A")

# 阶段 4: 落锤执行或是当场作废
if decision.payload["passed"]:
    log.commit("agent-A", intent_id, summary="Removed 47 checkpoints.")
else:
    log.abort("agent-A", ref_id=intent_id, reason="Rejected by peers.")
```

---

## 一场提案的生老病死

每一个协调共识动作，都逃不出这四个生命周期阶段：

```text
Stage 1: Intent (起意) — 肇事 agent 大声嚷嚷它准备干什么
Stage 2: Vote (投票)   — 同僚们在时间窗口内投出赞成或否决票
Stage 3: Decision (决议) — 记票后将生杀大权记录在案
Stage 4: Commit / Abort (落锤 / 弃绝) — 实际行动，要么干了，要么拉倒
```

每个阶段都会在日志尾部夯实一条记录，并带有一个毫无缝隙且单调递增的 `position`。这意味着只要你重播日志，谁挑的头、谁跳出来反对以及为什么反对，全能像看录像带一样完美还原。

---

## 拿它锁死那些搞破坏的操作

别把共识当成口头协议，把它变成一个死硬的前置安全门 (Gate)：达不到赞成票阈值，这扇门宁可憋死也绝不放行。

```python
from bene.shared_log import SharedLog

class SafetyGate:
    def __init__(self, log, voter_agents, required_approvals=1):
        self.log = log
        self.voter_agents = voter_agents
        self.required_approvals = required_approvals

    def request(self, agent_id, action, metadata=None):
        return self.log.intent(agent_id=agent_id, action=action, metadata=metadata)

    def execute(self, agent_id, intent_id):
        summary = self.log.tally(intent_id)
        decision = self.log.decide(intent_id=intent_id, agent_id=agent_id)
        if summary.approve >= self.required_approvals and decision.payload["passed"]:
            self.log.commit(agent_id, intent_id, summary="Approved. Executing.")
            return True
        self.log.abort(agent_id, ref_id=intent_id, reason="Insufficient approvals.")
        return False
```

想看活的代码？去跑 [examples/safety_voting.py](../examples/safety_voting.py)。

---

## 在黑框框里直接盯梢总线

不需要写半行 Python 代码，直接在终端里盯着看、加滤网、数人头：

```bash
# 抓取最近 20 条事记
uv run bene log tail

# 只盯着特定类型的事件看
uv run bene log tail --type intent --n 10

# 只盯着某个特务 agent 看
uv run bene log tail --agent <agent_id>

# 拉出一份总线活跃度审计报表
uv run bene log ls

# 强行吐出 JSON 以便接上 JQ 处理
uv run bene --json log tail | jq '.[] | select(.type == "decision")'
```

---

## 在 Claude Code 里调动总线

五把 MCP 专武，直接把这套协议暴露给了 Claude Code 或者任何 MCP 客户端：

```text
shared_log_intent  — 宣告起意 (阶段 1)
shared_log_vote    — 丢出选票 (阶段 2)
shared_log_decide  — 盖章决议 (阶段 3)
shared_log_append  — 强行挂载 commit/result/abort/policy/mail 记录
shared_log_read    — 翻阅这本流水账
```

---

## 在 Python 里玩转总线

### 提案，开票，决议

```python
# 阶段 1
intent_id = log.intent(agent_id, action, metadata=None)

# 阶段 2
entry = log.vote(agent_id, intent_id, approve=True, reason="")

# 先偷瞄一眼票数但不盖章
summary = log.tally(intent_id)
# summary.approve, summary.reject, summary.passed

# 阶段 3 (随便你调几次，极其安全)
decision = log.decide(intent_id, agent_id)
# decision.payload == {"passed": True, "approve": 2, "reject": 0, "abstain": 0}
```

### 收场：干了、算了、或者抛出战果

```python
commit = log.commit(agent_id, intent_id, summary="Done.", metadata={})
abort  = log.abort(agent_id, ref_id=intent_id, reason="Vetoed.")
result = log.result(agent_id, ref_id=None, payload={"accuracy": 0.87})
```

### 铁血规矩和飞鸽传书

```python
# 立下铁规矩 (人类或者上位 supervisor 可以强行注射进去)
log.policy(agent_id, rule="Never delete production data without 2 approvals.")

# 异步给其他 agent 塞小纸条
log.mail(from_agent, to_agent, message="Hey, can you handle task X?", ref_id=None)
```

### 录像重播，加滤镜，抽丝剥茧

```python
# 顺着某个指针往后拉出所有的流水
entries = log.read(since_position=0, limit=100)

# 加滤镜
entries = log.read(type="intent", agent_id="agent-A")

# 按照时间顺手抓取最后 N 条
entries = log.tail(n=20)

# 抽丝剥茧：把一条提案连同后续所有缠在上面的选票和决议全拽出来
entries = log.thread(root_id=intent_id)
```

### 霸王硬上弓

嫌没有趁手的皮套？直接自己硬敲：

```python
entry = log.append(agent_id, type="result", payload={"key": "value"}, ref_id=None)
```

---

## 这些名头到底都是些什么货色

一共 8 种事件类型，包揽了整个协议的 4 个阶段，还白送你两个额外的协调手段：

| 种类 | 宿命 |
|------|---------|
| `intent` | 宣告一起即将发生的行动计划 (LogAct 阶段 1) |
| `vote` | 针对某起宣告投出赞同或反对票 (阶段 2) |
| `decision` | 计票后拍板的最终决议 (阶段 3) |
| `commit` | 宣告破门并顺利执行了行动 (阶段 4) |
| `result` | 终局产出物或者战利品 |
| `abort` | 提案被打回，或是行动宣告破产流产 |
| `policy` | 悬在头顶的铁律，通常由上位者或人类强行注入 |
| `mail` | 粗暴的 agent-to-agent 异步飞鸽传书 |

---

## 一张表，零服务

整个重型的协同层，被彻底压扁塞进了你的 bene 数据库里的这一张表里：

```sql
CREATE TABLE shared_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    position    INTEGER UNIQUE NOT NULL,   -- 绝对单调递增，无缝隙
    type        TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    ref_id      INTEGER REFERENCES shared_log(log_id),
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
```

还是那句话，没有任何一滴数据走出了你的机器：不用单独拉起什么守护进程，不用监听任何端口。直接一把 `cp` 拷走这个 `.db` 文件，你就连带着把每一张提案、每一张选票以及每一记落锤的铁证全考走了。

---

## 去看真正的火拼现场

四个阶段外加所有条目的真枪实弹端到端演练，全在这里：[examples/shared_log_coordination.py](../examples/shared_log_coordination.py)。

---

## 血脉渊源 (Lineage)

这套架构设计的正统血脉是 **LogAct: Enabling Agentic Reliability via Shared Logs** — Balakrishnan, Shi, Lu, Goel, Baral, Lyu, Dredze (Meta, 2026), [arXiv:2604.07988](https://arxiv.org/abs/2604.07988)。

bene 毫刀不改地继承了原论文里的核心精华：

- 将一条只能追加 (append-only) 的 log 捧为整个协同网的唯一真相源 (ground truth)
- 严守 intent → vote → decision 这三段论的安全闸门
- 严密的位置定序 (position-ordering) 机制，强制逼迫所有的并发 agent 咽下一模一样的历史事件流
- 保留 `policy` 记录类别，死守人类随时可以介入干预的通道

但 bene 也在以下这些地方扯起了自己的反旗：

- 我们的 log 就是一张跑在 WAL 模式下的 SQLite 表，而不是什么他妈的连在网线上的远端服务。
- 在 LogAct 的五大金刚之外，我们私自塞进了两个新种族：`policy` 和 `mail`。
- 我们搓了个 `thread()` 外挂，让你能一键把沾了边的一整串审计黑产全顺藤摸瓜拽出来。
- 在这里，`agent_id` 是一等公民，被死死地焊进了整个 bene agent 的生命周期底座里。
