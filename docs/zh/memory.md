# 跨代记忆库 (Cross-Agent Memory)

把踩过的坑记下来一次，之后无论是下一轮迭代、下一个 session 还是另外一台 worker 上跑的任何 agent，都能直接把它翻出来。

> **一个 agent 吃过的亏，直接变成全场 agent 的共有 context：这就是整个项目共享的、支持全文检索的唯一记忆总库。**

本方案的核心构想，是对 [claude-mem](https://github.com/thedotmack/claude-mem) (AGPL-3.0) 的一次 clean-room 级别的重构演进 —— 详见 [致谢](#credits)。

---

## 快速起步

把你的数据库连接塞给 `MemoryStore`；只要是跟这个 `.db` 绑在同一个绳上的 agent，就能同享这份记忆。

```python
from bene import Bene
from bene.memory import MemoryStore

bene = Bene("project.db")
mem  = MemoryStore(bene.conn)

# 兵马未动粮草先行，得先有个 agent_id —— memory 的每一条记录都得靠外键死死咬住一个主人
agent_id = bene.spawn("proposer-iter-3")

# 任何一个 agent 都能往里头塞战果
mid = mem.write(
    agent_id=agent_id,
    content="Ensemble voting with 3 Sonnet calls achieved accuracy=0.847.",
    type="result",
    key="iter3-best",
    metadata={"accuracy": 0.847, "cost": 18.2},
)

# 而其它任意 agent 都能在全量记忆池里进行打捞
hits = mem.search("ensemble accuracy")
for h in hits:
    print(h.content)
```

想看活的？去跑 [examples/memory_search.py](../examples/memory_search.py)。

---

## 下笔前，先选好门派 (Type)

每一条记下来的账都得带个出处门派；那些专职扫雷的 agent 往往起手就是一句 filter to `error`。

| 门派 (Type) | 适用战场 |
|------|----------|
| `observation` | 运行时摸查到的底细，跑出来的一半结果 |
| `result` | 尘埃落定的最终产出，打出来的 benchmark 成绩 |
| `skill` | 能被反复白嫖的套路，可以直接抄的代码模板 |
| `insight` | 深度复盘，血泪教训 |
| `error` | 确认过眼神的死胡同，必须绕道走的坑 |

---

## 翻找先辈们的遗产

### `MemoryStore.search(query, limit, type, agent_id) -> list[MemoryEntry]`

发出去的查询会直接硬撞 SQLite 的 FTS5 引擎 (自带 porter 词干提取)，然后乖乖按 BM25 相关度评分排好队。

FTS5 原生的查询语法在这直接管用：

- 词组连坐: `"chain of thought"`
- 坚决不要: `reasoning NOT error`
- 兼收并蓄: `ensemble OR majority`
- 模糊通配: `accurac*`

```python
# 跨越血统门派的无差别撒网
hits = mem.search("ensemble voting math", limit=5)

# 专捞那些标了 'error' 的案底
errors = mem.search("JSON decode", type="error")

# 死盯着某一个特定 agent 查
hits = mem.search("ensemble", agent_id=agent_id)
```

---

## 录入、查阅和抹杀

### `MemoryStore.write(agent_id, content, type, key, metadata) -> int`

把一条记录钉进账本，并返回它的 `memory_id` 铭牌。

```python
mid = mem.write(
    agent_id="agent-01",
    content="Chain-of-thought prompting reduces errors by 23%.",
    type="skill",
    key="cot-numbered-steps",
    metadata={"benchmark": "math_rag"},
)
```

### `MemoryStore.list(agent_id, type, limit, offset) -> list[MemoryEntry]`

新来的排前面；可以用 agent 或者 type 收拢范围，还能用 `offset` 来翻页。

```python
# 把家底全亮出来
entries = mem.list()

# 只挑能当 skill 用的
skills = mem.list(type="skill", limit=20)

# 直接翻到第二页
page2 = mem.list(offset=20, limit=20)
```

### `MemoryStore.get(memory_id) -> MemoryEntry | None`

拿着主键 ID 去精准捞人。

### `MemoryStore.get_by_key(key, agent_id) -> MemoryEntry | None`

把挂着指定 key 的最新那条记录翻出来。

### `MemoryStore.delete(memory_id) -> bool`

抹除一条记忆；底层的触发器 (trigger) 会顺手把 FTS 里的搜索底根也一块烧掉。

### `MemoryStore.stats() -> dict`

拉出一份包含总数以及各大门派人丁细分的总账单。

---

## 让 Meta-Harness 替你记账

每一轮肉搏打完，meta-harness 都会自觉把变强了的 harnesses 和确诊的死穴全记下来；下一次 proposer 构思新点子时，它的 prompt 里就会凭空多出一块由过往搜索拼凑出来的 "跨世代记忆 (Cross-Session Memory)" 外挂模块。

**哪怕你中途重启过搜寻进程，再活过来的 proposer 脑子里依然清清楚楚地记得前辈们试过啥。**

```python
# 这两步是全自动的：
# 发现 harness 变强或者翻车时，_store_result() 会自动落笔写 memory
# 构思新变种时，proposer._load_memory_context() 会自动去捞 memory
```

---

## 从黑框框里直接下令

录入、查询和列表这三招都在 Shell 下留了后门；挂上 `--json` 就能直接串进你的自动化管道里。

```bash
# 录入一条新的长远记忆
uv run bene memory write <agent_id> "Ensemble voting improved accuracy by 12%." --type insight --key ensemble-v1

# 掏出全文检索引擎直接开查
uv run bene memory search "ensemble accuracy"
uv run bene memory search "JSON error" --type error

# 看看最近大家都记了些啥
uv run bene memory ls
uv run bene memory ls --type result --limit 5

# 强行吐出 JSON 格式以便接上 JQ 处理
uv run bene --json memory search "ensemble" | jq '.[].content'
```

---

## 在 Claude Code 里呼叫火力

任何通过 MCP 连上 BENE 的 agent，手里天然就攥着这三把针对 memory 的 tool:

```text
agent_memory_write   — 钉死一条记忆
agent_memory_search  — 跨越全场 agent 发动 FTS5 搜索
agent_memory_read    — 根据 memory_id 精准抓取或者直接列出近期流水
```

---

## 扒底：你的数据到底在哪？

一滴数据都走不出你的机器：所谓的记忆，无非就是跟你的 agent 们挤在同一个 `.db` 文件里的那张 SQLite 数据表 —— 你把这个文件考走，这满脑子的记忆也就跟着考走了。支撑搜索的则是一张 FTS5 虚拟表，背后的同步全靠数据库的原生触发器 (triggers) 硬扛。

```sql
CREATE TABLE memory (
    memory_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    type        TEXT NOT NULL DEFAULT 'observation'
                CHECK (type IN ('observation','result','skill','insight','error')),
    key         TEXT,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
    content, key,
    type UNINDEXED, agent_id UNINDEXED, memory_id UNINDEXED, created_at UNINDEXED,
    tokenize = 'porter unicode61'
);
-- FTS 的同步脏活，由 INSERT/UPDATE/DELETE triggers 统统包揽
```

---

## 致谢

让 agent 留下高度紧凑、随时可被检索的便签，以供后人白嫖 —— 这颗灵感的火种直接来自 Alex Newman 的开源项目 [claude-mem](https://github.com/thedotmack/claude-mem) ([@thedotmack](https://github.com/thedotmack))，遵从 AGPL-3.0 协议。但 BENE 在这颗种子上长出了截然不同的枝干：

- 底座直接换成了 SQLite FTS5，而不是在外面另起一套杂乱的文件堆。
- 打破了单体牢笼：支持一堆 agent 疯狂写入，另一堆 agent 疯狂读取。
- 引入了门派标签 (result, skill, error, insight, observation)，让信息检索时自带结构化的过滤网。
- 彻底让 meta-harness 学会了全自动吞吐和读取记忆。
