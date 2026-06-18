# 探秘 bene.db

用任何一款 SQLite 客户端直接打开 `bene.db`，你就能用最纯粹的 SQL 回答你的 agents 能引发的所有疑问：它们到底干了什么，写了哪些文件，脑子里记住了什么，以及你能把它们回滚到哪个时间点。本页面将 11 张表的使命全部拆解，为你指明它们能回答什么问题，详细记录每一个字段，并且备好了一堆可以直接复制粘贴的查询语句。

> **你整支 agent 舰队的所有状态，全部被打包在这唯一一个 SQLite 文件里 —— 查询它，用 `cp` 备份它；没有半个字节的数据会离开你的机器。**

当前的 Schema 已经推进到了 **v4** 版本，具体定义见 `bene/schema.py`。

---

<a id="overview"></a>

## 一份文件，十一张表

bene 将所有的数据统统放进一个开启了 WAL (预写式日志) 模式的 SQLite 数据库里。这里以 `agents` 表为核心，向下挂载了多张表 (`files`, `events`, `tool_calls`, `state`, `checkpoints`, `memory`, `agent_skills`)；`blobs` 则专门负责屯放 `files` 所指向的二进制字节肉身。`shared_log` 则用来记录 A2A 总线 (bus) 上的协同共识事件（虽然 `shared_log.agent_id` 记录的是发起方 agent 的名字，但出于解耦它并没有挂载指向 `agents` 的外键约束）：

```text
agents  ----<  files         (1:N - 每个 agent 拥有多份文件)
        ----<  tool_calls    (1:N - 每个 agent 发起多次工具调用)
        ----<  state         (1:N - 每个 agent 维护多对 KV 状态)
        ----<  events        (1:N - 每个 agent 产生多条事件流)
        ----<  checkpoints   (1:N - 每个 agent 留下多个检查点)

blobs   <----  files         (1:N - 多个文件可能共享同一个内容 blob)
```

这两条铁律贯穿全局：

- **Timestamps (时间戳)** 全部采用携带毫秒精度的 ISO 8601 文本格式，统一由 `strftime('%Y-%m-%dT%H:%M:%f', 'now')` 生成。
- **JSON 字段** —— 包括 `config`, `metadata`, `input`, `output`, `payload`, `value`, `file_manifest`, `state_snapshot` —— 必须永远塞入合法的 JSON 文本。

---

## 问题导向查询指南

| 遇到这个问题时... | 请查阅 |
|---|---|
| 这个 agent 到底干了什么？ | [events 事件流](#events) |
| 跑了什么 tool？输入是什么？耗时多久？ | [tool_calls 调用账本](#tool_calls-every-tool-invocation) |
| 到底生了几个 agent？它们还活着吗？ | [agents 花名册](#agents-the-roster) |
| agent 当前的作业状态 (短期记忆草稿) 是什么？ | [state 专属键值存储](#state-per-agent-key-value-memory) |
| agent 跨 session 还能记住啥？ | 查 `memory` + `memory_fts` —— 支持全文检索 (`SELECT … FROM memory_fts WHERE memory_fts MATCH '…'`); 详见 [memory.md](memory.md) |
| 我能回滚到哪里？ | [checkpoints 状态快照](#checkpoints-snapshots-you-can-return-to) |
| 这个 agent 到底写了什么东西？ | [files 虚拟文件系统](#files-the-virtual-filesystem) |
| 文件的字节肉身到底是怎么存的？ | [blobs 去重内容块](#blobs-deduplicated-content) |
| 这份文件经历过几次数据库迁移？ | [schema_version 迁移大账本](#schema_version-the-migration-record) |

---

## events

这就是 bene 的审计账本 (audit trail)。agent 的一举一动 —— 写文件、调 tool、生命周期切换、打 checkpoint —— 统统只能向这里追加写入 (append-only) 且永不篡改，因此你查出来的这串流水就是铁一般的事实。

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    idempotency_key TEXT
);
-- v4 版本的 schema 补上了一个部分唯一索引，以支撑安全的 (Temporal) 重试机制:
-- CREATE UNIQUE INDEX idx_events_idem ON events(agent_id, idempotency_key)
--   WHERE idempotency_key IS NOT NULL;
-- 同样的 `idempotency_key TEXT` 字段及部分唯一索引，在 `tool_calls` 和 `files` 表里也有。
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `event_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 单调递增，天然充当全局事件排序器。 |
| `agent_id` | TEXT | NOT NULL, FK -> agents | 该事件的肇事者。 |
| `event_type` | TEXT | NOT NULL | 下文列出的各类事件标识符。 |
| `payload` | TEXT | NOT NULL, 默认 `'{}'` | 事件相关的细节，统统打成 JSON 对象。 |
| `timestamp` | TEXT | NOT NULL, 自动生成 | 自动写入的 ISO 8601 毫秒级时间戳。 |
| `idempotency_key` | TEXT | 可空, 若有值则在单个 agent 内必须唯一 (v4) | 带着相同 key 复用的写入会被无视而不是产生重复数据 —— 这是支撑 Temporal 任务安全重试的核心。`tool_calls` 和 `files` 同样搭载此字段。 |

### 事件类型 (Event types)

bene 默认发射的标准 `event_type` 以及各自的 payload 长相（如果挂了 Temporal runtime，还会多吐几个额外类型）：

| Event Type 事件类型 | Payload 示例 | 触发场景 |
|---|---|---|
| `agent_spawn` | `{"name": "...", "parent_id": null, "config": {...}}` | 通过 `spawn()` 新建 agent 时 |
| `agent_pause` | `{}` | Agent 被暂停时 |
| `agent_resume` | `{}` | Agent 被唤醒恢复时 |
| `agent_kill` | `{}` | Agent 被强制处决时 |
| `agent_complete` | `{}` | Agent 顺利完工退场时 |
| `agent_fail` | `{"error": "..."}` | Agent 干砸了报错时 |
| `state_change` | `{"field": "status", "from": "initialized", "to": "running"}` | 发生状态跃迁时 |
| `file_read` | `{"path": "/src/app.py"}` | 从 VFS 里读文件时 |
| `file_write` | `{"path": "/src/app.py", "size": 1234, "version": 2}` | 往 VFS 里写文件时 |
| `file_delete` | `{"path": "/tmp/scratch.txt"}` | 从 VFS 删文件时 |
| `tool_call_start` | `{"call_id": "...", "tool_name": "fs_read"}` | 开始调 tool 时 |
| `tool_call_end` | `{"call_id": "...", "status": "success"}` | 调完 tool 时 |
| `llm_call` | `{"model": "...", "prompt_len": 1234, "input_tokens": 800, "output_tokens": 120, "cache_read_tokens": 0, "cache_creation_tokens": 0}` | 完成一次模型调用时 (仅 Temporal 运行时会发) |
| `checkpoint_create` | `{"checkpoint_id": "...", "label": "pre-refactor"}` | 刚切完一张 checkpoint 快照时 |
| `checkpoint_restore` | `{"checkpoint_id": "..."}` | 刚恢复完一次 checkpoint 快照时 |
| `error` | `{"message": "..."}` | 遇到运行时严重错误时 |
| `warning` | `{"message": "..."}` | 抛出运行时警告时 |

### 开箱即用的查询语句

```sql
-- 抽调某个 agent 完整的时间轴流水
SELECT event_id, event_type, payload, timestamp
FROM events
WHERE agent_id = '01HXYZ...'
ORDER BY event_id;

-- 这个 agent 在过去一小时里到底搞了什么名堂？
SELECT event_type, payload, timestamp
FROM events
WHERE agent_id = '01HXYZ...'
AND timestamp > strftime('%Y-%m-%dT%H:%M:%f', 'now', '-1 hour')
ORDER BY event_id;

-- 统计某个 agent 发出的各类事件数量
SELECT event_type, COUNT(*) as count
FROM events
WHERE agent_id = '01HXYZ...'
GROUP BY event_type
ORDER BY count DESC;

-- 全局系统活动概览
SELECT event_type, COUNT(*) as count
FROM events
GROUP BY event_type
ORDER BY count DESC;

-- 跨越所有 agent 找出所有的文件写入动作
SELECT e.agent_id, a.name,
       json_extract(e.payload, '$.path') as file_path,
       json_extract(e.payload, '$.size') as size,
       e.timestamp
FROM events e
JOIN agents a ON e.agent_id = a.agent_id
WHERE e.event_type = 'file_write'
ORDER BY e.timestamp DESC
LIMIT 20;
```

*背后的索引支撑: `idx_events_agent_time` (`agent_id, timestamp`) 以及 `idx_events_type` (`event_type`) —— 详情查阅文末的 [索引目录](#index-catalog)。*

---

## tool_calls: 每一笔工具调用账单

agent 调用工具的每一个动作都会带着它的输入、输出、耗时以及 token 花销一起入账 —— 一旦遇到卡死或是崩溃的调用，你完全可以逐笔核查，甚至能把嵌套调用还原成一条清晰的调用链。

```sql
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id         TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    tool_name       TEXT NOT NULL,
    input           TEXT NOT NULL,
    output          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','success','error','timeout')),
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    completed_at    TEXT,
    duration_ms     INTEGER,
    token_count     INTEGER,
    cost_usd        REAL DEFAULT 0.0,
    parent_call_id  TEXT REFERENCES tool_calls(call_id),
    error_message   TEXT
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `call_id` | TEXT | PRIMARY KEY | ULID，每次调用独一无二。 |
| `agent_id` | TEXT | NOT NULL, FK -> agents | 发起调用的 agent。 |
| `tool_name` | TEXT | NOT NULL | 跑的到底是什么 tool (比如 `fs_read`, `shell_exec`, `fs_write`)。 |
| `input` | TEXT | NOT NULL | 入参，直接序列化成 JSON。 |
| `output` | TEXT | 可空 | 出参 JSON；调用结束前保持 NULL。 |
| `status` | TEXT | NOT NULL, CHECK 约束 | 必须是 `pending`, `running`, `success`, `error`, `timeout` 其中之一。 |
| `started_at` | TEXT | NOT NULL, 自动生成 | 记录调用的初始时间戳。 |
| `completed_at` | TEXT | 可空 | 调用收摊时填入。 |
| `duration_ms` | INTEGER | 可空 | 调用收摊时算出的真实耗时 (毫秒)。 |
| `token_count` | INTEGER | 可空 | 触发本次 tool 使用的那次模型请求究竟烧了多少个 token。 |
| `cost_usd` | REAL | 默认 0.0 | 预留的美元计价估算字段。 |
| `parent_call_id` | TEXT | FK -> tool_calls(call_id), 可空 | 指向父级调用，借此把嵌套调用串成一条清晰的跟踪链。 |
| `error_message` | TEXT | 可空 | 只有当状态变成 `error` 时才会填入的错误明细。 |

### 开箱即用的查询语句

```sql
-- 抓取某个 agent 最近的 tool 账单
SELECT call_id, tool_name, status, duration_ms, token_count
FROM tool_calls
WHERE agent_id = '01HXYZ...'
ORDER BY started_at DESC
LIMIT 20;

-- 算算各 agent 的 token 燃烧账单
SELECT a.name, SUM(tc.token_count) as total_tokens, COUNT(*) as calls
FROM tool_calls tc
JOIN agents a ON tc.agent_id = a.agent_id
WHERE tc.status = 'success'
GROUP BY tc.agent_id
ORDER BY total_tokens DESC;

-- 把失败的 tool 调用连同报错细则全翻出来
SELECT agent_id, tool_name, error_message, started_at
FROM tool_calls
WHERE status = 'error'
ORDER BY started_at DESC;

-- 按照工具类别看平均耗时
SELECT tool_name, AVG(duration_ms) as avg_ms, COUNT(*) as calls
FROM tool_calls
WHERE status = 'success'
GROUP BY tool_name
ORDER BY avg_ms DESC;

-- 追踪一条 tool 嵌套调用链 (通过递归 CTE)
WITH RECURSIVE chain AS (
    SELECT call_id, tool_name, parent_call_id, 0 as depth
    FROM tool_calls WHERE call_id = 'target-call-id'
    UNION ALL
    SELECT tc.call_id, tc.tool_name, tc.parent_call_id, c.depth + 1
    FROM tool_calls tc JOIN chain c ON tc.parent_call_id = c.call_id
)
SELECT * FROM chain ORDER BY depth;
```

*背后的索引支撑: `idx_tool_calls_agent` (`agent_id, started_at`), `idx_tool_calls_tool` (`tool_name`), 以及 `idx_tool_calls_status` (`status`) —— 详情查阅文末的 [索引目录](#index-catalog)。*

---

## agents: 花名册

一表包揽所有 agent 户口：到底有谁存在，谁生了谁，以及此刻它们各自处于何种生命体征状态。

```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_id       TEXT REFERENCES agents(agent_id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    status          TEXT NOT NULL DEFAULT 'initialized'
                    CHECK (status IN ('initialized','running','paused','completed','failed','killed')),
    config          TEXT NOT NULL DEFAULT '{}',
    metadata        TEXT NOT NULL DEFAULT '{}',
    pid             INTEGER,
    last_heartbeat  TEXT
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `agent_id` | TEXT | PRIMARY KEY | ULID —— 唯一且原生自带时间排序能力。 |
| `name` | TEXT | NOT NULL | 你赋予它的代号 (比如 "test-writer")。 |
| `parent_id` | TEXT | FK -> agents(agent_id), 可空 | 如果它是被别的 agent 孵化出来的，这里就有值；根节点则为 NULL。 |
| `created_at` | TEXT | NOT NULL, 自动生成 | 诞生时刻敲下的 ISO 8601 钢印。 |
| `status` | TEXT | NOT NULL, CHECK 约束 | 必须是 `initialized`, `running`, `paused`, `completed`, `failed`, `killed` 其中之一。 |
| `config` | TEXT | NOT NULL, 默认 `'{}'` | 该 agent 专属的 JSON 配置文件 (例如 `{"force_model": "deepseek-r1-70b"}`)。 |
| `metadata` | TEXT | NOT NULL, 默认 `'{}'` | 一块任你塞入任意格式化信息的自由 JSON 空地。 |
| `pid` | INTEGER | 可空 | 该 agent 苟活在操作系统里时对应的进程 ID。 |
| `last_heartbeat` | TEXT | 可空 | 最后的脉搏跳动时间，ISO 8601 格式。 |

### 开箱即用的查询语句

```sql
-- 揪出所有还在奔跑的 agents
SELECT agent_id, name, last_heartbeat
FROM agents WHERE status = 'running';

-- 查找被某位 "父辈" 孵化出的所有徒子徒孙
SELECT agent_id, name, status
FROM agents WHERE parent_id = '01HXYZ...';

-- 看看所有 agent 目前生死状态的盘点
SELECT status, COUNT(*) as count
FROM agents GROUP BY status;

-- 抓出那些心跳骤停的僵尸 agent (5分钟没心跳的)
SELECT agent_id, name, last_heartbeat
FROM agents
WHERE status = 'running'
AND last_heartbeat < strftime('%Y-%m-%dT%H:%M:%f', 'now', '-5 minutes');
```

*背后的索引支撑: `idx_agents_status` (`status`) 以及 `idx_agents_parent` (`parent_id`) —— 详情查阅文末的 [索引目录](#index-catalog)。*

---

## state: 专属的键值存储草稿本

只要是一个能写进 JSON 里的数据，就能存在这里：每个 agent 都会圈定一块自己的专属键值命名空间，把脑子里随时要查的进度和状态记在账上。

```sql
CREATE TABLE IF NOT EXISTS state (
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (agent_id, key)
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `agent_id` | TEXT | NOT NULL, FK -> agents, PK 的一半 | 领地主人 —— 主键的前半段。 |
| `key` | TEXT | NOT NULL, PK 的另一半 | 键名 (比如 `conversation`, `iteration`, `progress`)。 |
| `value` | TEXT | NOT NULL | 塞进去的 JSON 文本：字符串、数字、数组或者是嵌套对象。 |
| `updated_at` | TEXT | NOT NULL, 自动生成 | 只要有修改就立马刷新这根时间轴。 |

### 运作机制拆解

- 这个由 `(agent_id, key)` 咬合而成的联合主键既保证了键名在 agent 地界内的唯一性，也成为了支撑 `ON CONFLICT` 覆写操作的核心基石。
- `set_state()` 方法实际上是在执行 `INSERT ... ON CONFLICT DO UPDATE`，因此，重新塞入一个已存在的 key 就能直接完成一次原子级别的旧值换血。
- CCR 会顺手把 `conversation`、`iteration`、`task` 和 `result` 等记录丢在这里 —— 于是，你距离把一个 agent 的祖宗八代聊天记录全翻出来，只差一句 SELECT。

### 开箱即用的查询语句

```sql
-- 掏空某个 agent 的所有底牌
SELECT key, value, updated_at
FROM state
WHERE agent_id = '01HXYZ...'
ORDER BY key;

-- 单独撬开某个指定的值
SELECT value FROM state
WHERE agent_id = '01HXYZ...' AND key = 'iteration';

-- 看看哪几个 agent 熬到了多少个迭代轮次
SELECT s.agent_id, a.name, s.value as iteration
FROM state s
JOIN agents a ON s.agent_id = a.agent_id
WHERE s.key = 'iteration'
ORDER BY CAST(s.value AS INTEGER) DESC;

-- 盘点一共有哪些 key 最受全场 agent 欢迎
SELECT key, COUNT(*) as agent_count
FROM state
GROUP BY key
ORDER BY agent_count DESC;
```

---

## checkpoints: 随时退回的时空快照

所谓的 checkpoint 就是把某个 agent 的文件系统和所有 state 数据直接冻成一块标本，这就意味着任何一记昏招都不再是末日：还原它，对比它，然后装作什么都没发生过一样继续跑。

```sql
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id   TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    label           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    event_id        INTEGER REFERENCES events(event_id),
    file_manifest   TEXT NOT NULL,
    state_snapshot  TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}'
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `checkpoint_id` | TEXT | PRIMARY KEY | ULID。 |
| `agent_id` | TEXT | NOT NULL, FK -> agents | 快照从属人。 |
| `label` | TEXT | 可空 | 可选的标签注释 (比如 `"pre-refactor"`, `"auto-iter-10"`)。 |
| `created_at` | TEXT | NOT NULL, 自动生成 | 拍下快照的刹那，ISO 8601。 |
| `event_id` | INTEGER | FK -> events(event_id), 可空 | 死死锚定在当时事件流里的高水位标记；你要做 diff 就得靠它。 |
| `file_manifest` | TEXT | NOT NULL | 一长串文件花名册的 JSON 数组：`[{"path": "...", "content_hash": "...", "version": N}, ...]`。 |
| `state_snapshot` | TEXT | NOT NULL | 拍快照时的 KV 状态底包：`{"key1": value1, "key2": value2, ...}`。 |
| `metadata` | TEXT | NOT NULL, 默认 `'{}'` | 额外的 JSON 数据，随你怎么用。 |

### 开箱即用的查询语句

```sql
-- 罗列某个 agent 留下的所有快照足迹
SELECT checkpoint_id, label, created_at, event_id
FROM checkpoints
WHERE agent_id = '01HXYZ...'
ORDER BY created_at;

-- 把某个快照拿去体检 (算算打包了多少文件，多少个 state 键)
SELECT
    checkpoint_id,
    label,
    created_at,
    json_array_length(file_manifest) as file_count,
    (SELECT count(*) FROM json_each(state_snapshot)) as state_keys
FROM checkpoints
WHERE agent_id = '01HXYZ...';

-- 捞出那些由系统自动定期生成的 checkpoints
SELECT checkpoint_id, label, created_at
FROM checkpoints
WHERE label LIKE 'auto-iter-%'
ORDER BY created_at;

-- 拆包检视某一个快照里究竟藏了哪些文件
SELECT
    json_extract(value, '$.path') as path,
    json_extract(value, '$.content_hash') as hash,
    json_extract(value, '$.version') as version
FROM checkpoints, json_each(file_manifest)
WHERE checkpoint_id = '01HABC...';
```

*背后的索引支撑: `idx_checkpoints_agent` (`agent_id, created_at`) —— 详情查阅文末的 [索引目录](#index-catalog)。*

---

## files: 虚拟文件系统

agent 敲下的任何一个字节，都会在这条专属赛道里生出崭新的版本号记录 —— 所有陈旧版本的尸骨都仍旧躺在那里任你查询；并且哪怕你下了删除指令，所谓的删除也不过是把它雪藏 (soft delete) 起来而已，它的身世历史绝不会因此陪葬。

```sql
CREATE TABLE IF NOT EXISTS files (
    file_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    path            TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT,
    size            INTEGER NOT NULL DEFAULT 0,
    mode            INTEGER NOT NULL DEFAULT 33188,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    modified_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    version         INTEGER NOT NULL DEFAULT 1,
    deleted         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(agent_id, path, version)
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `file_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 内部主键标号。 |
| `agent_id` | TEXT | NOT NULL, FK -> agents | 领地主人；一切查找必须以此起手过滤。 |
| `path` | TEXT | NOT NULL | 强制绝对路径并经由 POSIX 规格化处理 (例如 `/src/main.py`)。 |
| `is_dir` | INTEGER | NOT NULL, 默认 0 | 标为 1 则意味着这是个目录。 |
| `content_hash` | TEXT | 可空 | 拿到这个去 `blobs` 里提取正主的 SHA-256 钥匙；对于目录则恒为 NULL。 |
| `size` | INTEGER | NOT NULL, 默认 0 | 没做压缩之前的文件裸字节数。 |
| `mode` | INTEGER | NOT NULL, 默认 33188 | Unix 风格权限位；33188 等价于 `0o100644` (常规文件, rw-r--r--)。 |
| `created_at` | TEXT | NOT NULL, 自动生成 | 记录这具版本化化身降生那一刻。 |
| `modified_at` | TEXT | NOT NULL, 自动生成 | 记录你最后一次去戳它的时刻。 |
| `version` | INTEGER | NOT NULL, 默认 1 | 对同一条路径每次下笔，这里就乖乖 +1。 |
| `deleted` | INTEGER | NOT NULL, 默认 0 | 标为 1 即为软删除雪藏：在常规列表查询里蒸发，但作为历史陈迹保留，以便 checkpoint 随时诈尸还魂。 |

这个压住全场的 `UNIQUE(agent_id, path, version)` 约束牢牢守死了版本更替的底线 —— 一切都必须是一个 agent 下面、一条路径里面独一无二的版本号。

### 开箱即用的查询语句

```sql
-- 把某个 agent 辖区内还活着的活动文件统统列出来
SELECT path, size, version, modified_at
FROM files
WHERE agent_id = '01HXYZ...' AND deleted = 0 AND is_dir = 0
ORDER BY path;

-- 把某个特定文件的过往版本底裤也给翻出来
SELECT version, content_hash, size, created_at, deleted
FROM files
WHERE agent_id = '01HXYZ...' AND path = '/src/app.py'
ORDER BY version;

-- 查看某个目录下面一层的直系子集内容
SELECT path, is_dir, size, modified_at
FROM files
WHERE agent_id = '01HXYZ...'
AND deleted = 0
AND path LIKE '/src/%'
AND path NOT LIKE '/src/%/%'
AND path != '/src';

-- 盘点各个 agent 的仓库究竟吃掉了多少硬盘配额
SELECT agent_id, SUM(size) as total_bytes, COUNT(*) as file_count
FROM files
WHERE deleted = 0 AND is_dir = 0
GROUP BY agent_id
ORDER BY total_bytes DESC;
```

*背后的索引支撑: `idx_files_agent_path` (`agent_id, path`，带有局部过滤 `WHERE deleted = 0`) 以及 `idx_files_agent` (`agent_id`) —— 详情查阅文末的 [索引目录](#index-catalog)。*

---

## blobs: 彻底去重的内容块

文件里的肉身字节被死死地捏在 SHA-256 哈希值名下保管，只此一份 —— 如果两个 agent 碰巧写了丝毫不差的内容，系统只会在磁盘里落下唯一一份 blob，而且还是被压缩封印过的。

```sql
CREATE TABLE IF NOT EXISTS blobs (
    content_hash    TEXT PRIMARY KEY,
    content         BLOB NOT NULL,
    compressed      INTEGER NOT NULL DEFAULT 0,
    ref_count       INTEGER NOT NULL DEFAULT 1
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `content_hash` | TEXT | PRIMARY KEY | 未压缩裸数据的 SHA-256 十六进制签名。 |
| `content` | BLOB | NOT NULL | 实打实的字节 —— 如果压缩标记被点亮，这就是一段 zstd 压缩包。 |
| `compressed` | INTEGER | NOT NULL, 默认 0 | 1 = 该段数据已遭 zstd 压缩，0 = 原汁原味的裸片。 |
| `ref_count` | INTEGER | NOT NULL, 默认 1 | 有多少条 files 里的记录是指向这里的；删掉文件记录就递减，跌落到 <= 0 随时准备拉去火化 (回收)。 |

### 运作机制拆解

- **极致去重。** 第二次尝试把一模一样的东西塞进来，系统连一根毛都不会往下存，只会在 `ref_count` 上无情地加个一。
- **全系压缩。** 默认强制开启：所有字节在落盘前先被抓去过一遍 zstandard level 3，同时那个 `compressed` 标签负责告诉读取端在提取时别忘了先过个解压漏斗。
- **冷酷回收 (Garbage collection)。** `BlobStore.gc()` 发作起来，所有 `ref_count <= 0` 的行统统灰飞烟灭。这样做没一点毛病，因为所谓的软删除文件依旧会死死拽着自己的 `content_hash`，所以哪怕是被扔进垃圾桶的文件，凭 checkpoint 依然能顺理成章地捞出全尸。

### 开箱即用的查询语句

```sql
-- 调出 Blob 存储仓库的大体检报表
SELECT
    COUNT(*) as total_blobs,
    SUM(LENGTH(content)) as total_stored_bytes,
    SUM(ref_count) as total_references
FROM blobs;

-- 抓出那些无家可归随时会被物理超度的幽灵 blob
SELECT content_hash, LENGTH(content) as stored_size, ref_count
FROM blobs
WHERE ref_count <= 0;

-- 拉出按体量排名的全场前十大巨兽 blob
SELECT content_hash, LENGTH(content) as stored_bytes, ref_count
FROM blobs
ORDER BY LENGTH(content) DESC
LIMIT 10;

-- 看看哪些 blob 被不止一个文件高频白嫖
SELECT content_hash, ref_count
FROM blobs
WHERE ref_count > 1
ORDER BY ref_count DESC;
```

---

## schema_version: 迁移大账本

一横一竖只记录一条迁移指令，这样随便抛出一个 `bene.db` 的克隆体，它自己就能用这本账册自证清白：我究竟搭载了哪个阶段的骨架。

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

### 字段说明

| 字段 | 类型 | 约束 | 描述 |
|---|---|---|---|
| `version` | INTEGER | PRIMARY KEY | 迁移序列号。当前最新推进到了: 4。 |
| `applied_at` | TEXT | NOT NULL, 自动生成 | 执行这波迁移的确切时刻。 |

### 迁移动力学机制

- 初次开荒建库时，直接把版本 4 硬凿进表里。
- 在后续启动时，如果库里记载的版本落后于当前代码里锁定的 `SCHEMA_VERSION`，系统就会通过 `_apply_migrations()` 一阶一阶地把它暴力推向前沿。
- 未来的更新，会在 `bene/schema.py` 里统一按 `if from_version < N:` 规矩落座。

### 开箱即用的查询语句

```sql
-- 查查当前的 schema 究竟推进到了哪一版
SELECT MAX(version) as current_version FROM schema_version;

-- 拉出整个从古到今的迁移编年史
SELECT version, applied_at FROM schema_version ORDER BY version;
```

---

<a id="relationships"></a>

## 表与表是如何在暗中咬合的

schema 内部的每根引线，在这里一览无遗：

```text
agents.agent_id    ----<  files.agent_id           (一个 agent 坐拥多份文件)
agents.agent_id    ----<  tool_calls.agent_id      (一个 agent 发起多笔 tool 调用)
agents.agent_id    ----<  state.agent_id           (一个 agent 维系多条 state 状态键)
agents.agent_id    ----<  events.agent_id          (一个 agent 产生多条流转事件)
agents.agent_id    ----<  checkpoints.agent_id     (一个 agent 刻下多座 checkpoint 墓碑)
agents.agent_id    <---   agents.parent_id         (血脉相连的自我嵌套)
blobs.content_hash <---   files.content_hash       (同一坨血肉对应多张皮囊)
tool_calls.call_id <---   tool_calls.parent_call_id (层层嵌套的调用闭环链条)
events.event_id    <---   checkpoints.event_id     (把 checkpoint 钢钉直接打穿事件流)
```

这些连线可不是画在纸上的涂鸦。所有的牵扯都会被强制通过 `PRAGMA foreign_keys=ON` 让底层的 SQLite 执行冷血拒签 —— 任何文件休想去投靠一个根本不存在的幽灵 agent。

---

<a id="index-reference"></a>

## 索引目录

随着 schema 下发的每一把索引利器，以及它们所背负的特定狩猎指标：

| 所在表 | 索引代号 | 横跨字段 | 是否偏袒 (Partial) | 服役使命 |
|---|---|---|---|---|
| agents | `idx_agents_status` | `status` | 否 | 借用生命周期大类去大筛 agent |
| agents | `idx_agents_parent` | `parent_id` | 否 | 揪出子嗣 |
| files | `idx_files_agent_path` | `agent_id, path` | 是 (`deleted=0`) | 排除掉软删除垃圾后的极速文件拔查 |
| files | `idx_files_agent` | `agent_id` | 否 | 把某个 agent 名下的破烂全抖搂出来 |
| tool_calls | `idx_tool_calls_agent` | `agent_id, started_at` | 否 | 依照时间轴铺开的调用长卷 |
| tool_calls | `idx_tool_calls_tool` | `tool_name` | 否 | 认清具体到底用了哪件法宝 |
| tool_calls | `idx_tool_calls_status` | `status` | 否 | 顺着状态把调用抠出来 |
| events | `idx_events_agent_time` | `agent_id, timestamp` | 否 | 把事件串联回时间长河 |
| events | `idx_events_type` | `event_type` | 否 | 依据事件种姓展开过滤 |
| checkpoints | `idx_checkpoints_agent` | `agent_id, created_at` | 否 | 按资排辈地罗列出来的快照履历 |
