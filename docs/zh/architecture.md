# BENE 架构解析

BENE 为每个 agent 提供私有文件系统、可回放的事件轨迹（event trail），以及清晰可查的模型路由路径 —— 所有这一切都运行在由同一个 SQLite 后端支撑的 runtime 中。

> **当你要追踪一个来自 MCP 或 CLI 的请求，看它如何穿过 agent 执行层，最终落入可以被复制、查询、checkpoint 甚至恢复的数据库中时，本页面就是你的地图。**

这套架构只承担三项工作：保持 agent 状态便携 (portable)，保持 agent 动作隔离 (isolated)，保持模型执行过程透明 (understandable)。下方的章节编排契合了运维者典型的 debug 路径：首先看请求流，其次看存储状态，最后看承载和保护状态的各个子系统。

---

## 目录

1. [数据流转 (Data Flow)](#数据流转-data-flow)
2. [系统全景 (System Overview)](#系统全景-system-overview)
3. [Runtime 与可观测性边界 (Runtime And Observability Boundary)](#runtime-与可观测性边界-runtime-and-observability-boundary)
4. [VFS 引擎 (VFS Engine)](#vfs-引擎-vfs-engine)
5. [隔离模型 (Isolation Model)](#隔离模型-isolation-model)
6. [CCR 执行循环 (CCR Execution Loop)](#ccr-执行循环-ccr-execution-loop)
7. [Tier 路由器 (Tier Router)](#tier-路由器-tier-router)
8. [MCP Server 整合 (MCP Server Integration)](#mcp-server-整合-mcp-server-integration)
9. [设计哲学 (Design Philosophy)](#设计哲学-design-philosophy)

---

## 数据流转 (Data Flow)

当你需要弄清 "当 client 启动一个 agent 时到底发生了什么" 时，从这里看起。请求从 MCP server 或 CLI 进入，在 `Bene` 核心层中生成一个 agent，将执行权移交给 Claude Code Runner (CCR)，然后在返回结果前，记录每一次有意义的状态跃迁。

### 完整请求流 (MCP Client 到 Model)

```text
Claude Code                BENE MCP Server              BENE Core
    |                           |                           |
    |-- agent_spawn(task) ----->|                           |
    |                           |-- afs.spawn() ----------->|
    |                           |<-- agent_id --------------|
    |                           |                           |
    |                           |-- ccr.run_agent() ------->|
    |                           |                           |
    |                           |   +-- CCR Loop ----------+|
    |                           |   |                       |
    |                           |   |  构建 system prompt     |
    |                           |   |  设定 state             |
    |                           |   |       |               |
    |                           |   |       v               |
    |                           |   |  Tier 路由器            |
    |                           |   |   |                   |
    |                           |   |   | classify() 分类    |
    |                           |   |   | 选择 model          |
    |                           |   |   | 压缩 context        |
    |                           |   |   |       |           |
    |                           |   |   |       v           |
    |                           |   |   |  VLLMClient       |
    |                           |   |   |  POST /v1/chat/   |
    |                           |   |   |  completions      |
    |                           |   |   |       |           |
    |                           |   |   |       v           |
    |                           |   |   |  vLLM 实例         |
    |                           |   |   |  (本地 GPU)        |
    |                           |   |   |       |           |
    |                           |   |   |<------+           |
    |                           |   |   |                   |
    |                           |   |  解析 response         |
    |                           |   |  执行 tool calls       |
    |                           |   |  记录日志到 tool_calls  |
    |                           |   |  记录日志到 events      |
    |                           |   |  更新 state            |
    |                           |   |  自动 checkpoint       |
    |                           |   |       |               |
    |                           |   |  [循环 或 结束]         |
    |                           |   +-- End Loop -----------+
    |                           |                           |
    |                           |<-- result ----------------|
    |<-- {agent_id, result} ----|                           |
    |                           |                           |
```

这张图是你排查故障的最快路径。如果 `agent_spawn` 返回了但 agent 状态没变，去查 CCR；如果 CCR 跑起来了但没收到模型回复，查 Tier 路由器和 vLLM client；如果模型回复了但文件看上去不对，去查该 agent 的 `tool_calls`、`events` 以及 checkpoints。

### 静态数据分布 (SQLite Schema)

```text
+------------------+      +------------------+
|     agents       |      |      blobs       |
|------------------|      |------------------|
| agent_id (PK)    |      | content_hash (PK)|
| name             |      | content (BLOB)   |
| parent_id (FK)   |      | compressed       |
| status           |      | ref_count        |
| config (JSON)    |      +--------+---------+
| metadata (JSON)  |               ^
| pid              |               | content_hash
| last_heartbeat   |               |
+--------+---------+      +--------+---------+
         |                |      files       |
         | agent_id       |------------------|
         |                | file_id (PK)     |
         +--------------->| agent_id (FK)    |
         |                | path             |
         |                | content_hash (FK)|---+
         |                | version          |   |
         |                | deleted          |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|   tool_calls     |   |
         |                |------------------|   |
         |                | call_id (PK)     |   |
         |                | agent_id (FK)    |   |
         |                | tool_name        |   |
         |                | input (JSON)     |   |
         |                | output (JSON)    |   |
         |                | status           |   |
         |                | duration_ms      |   |
         |                | token_count      |   |
         |                | parent_call_id   |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|     state        |   |
         |                |------------------|   |
         |                | agent_id (FK,PK) |   |
         |                | key (PK)         |   |
         |                | value (JSON)     |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|    events        |   |
         |                |------------------|   |
         |                | event_id (PK)    |   |
         |                | agent_id (FK)    |   |
         |                | event_type       |   |
         |                | payload (JSON)   |   |
         |                | timestamp        |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|  checkpoints     |   |
                          |------------------|   |
                          | checkpoint_id(PK)|   |
                          | agent_id (FK)    |   |
                          | label            |   |
                          | event_id (FK)    |   |
                          | file_manifest    |---+
                          | state_snapshot   |
                          +------------------+
```

所有承载可变数据的表都以 `agent_id` 划定边界；所有的文件内容都通过 `content_hash` 进行寻址；所有的 checkpoint 都直接锚定到同一条事件流 (event stream) 中。正是这种设计，让整个 runtime 只需要一个 `.db` 文件就能运转。

### 并发模型 (Concurrency Model)

```text
Thread 1 (Agent A)         Thread 2 (Agent B)        Thread 3 (Agent C)
       |                          |                          |
       v                          v                          v
  thread-local conn          thread-local conn          thread-local conn
       |                          |                          |
       +----------- SQLite WAL mode (并发读) ---------------+
       |                          |                          |
       v                          v                          v
  写入 (串行)                读取 (并发)                读取 (并发)
```

SQLite WAL 模式允许海量并发读，但写操作串行。BENE 通过 `threading.local()` 为每个线程分配独立连接来配合这一点，同时 CCR 的信号量 (semaphore) 对活跃的 agent 循环进行了熔断控制，以防并行任务耗尽资源。`busy_timeout` 机制使得在抛出错误前，数据库锁争用的重试时间可长达 30000ms (30秒)。

---

## 系统全景 (System Overview)

BENE 是界定 agent 工作的 runtime 边界。外部 client 直接和 CLI 或 MCP server 对话；agent 循环则依赖 CCR 和 Tier 路由器；而所有持久化的状态都扎根于 `Bene` 核心层及其底层 SQLite。

```text
                      外部客户端
                    (Claude Code, CLI)
                           |
                           v
        +------------------------------------------+
        |           MCP Server / CLI               |
        |          (bene.mcp / bene.cli)            |
        +-----+------------------+-----------------+
              |                  |
              v                  v
     +----------------+  +----------------+
     |      CCR       |  |     Tier       |
     | 执行循环        |->|    路由器     |---> vLLM 实例组
     | (bene.ccr)     |  | (bene.router)  |     (httpx)
     +-------+--------+  +----------------+
             |
             v
     +------------------------------------------+
     |            BENE Core (Bene)            |
     |              (bene.core)                  |
     |                                           |
     |  +----------+ +--------+ +-------------+ |
     |  | BlobStore| | Event  | | Checkpoint  | |
     |  | (blobs)  | | Journal| | Manager     | |
     |  +----------+ +--------+ +-------------+ |
     |               |                           |
     |               v                           |
     |      +------------------+                 |
     |      |   SQLite (.db)   |                 |
     |      |   WAL mode       |                 |
     |      +------------------+                 |
     +------------------------------------------+
```

**包名:** `bene`
**CLI 入口:** `bene` (定义在 `bene.cli.main:cli`)
**配置文件:** `bene.yaml`

整个系统最核心的对象是 `Bene` (实现在 `bene/core.py`)。它将 Blob 存储区、事件日志、checkpoint 管理器、虚拟文件系统以及状态存储组合在了一起。Runner 和 MCP server 直接调用这个核心组件，而不是自己去重复造轮子搞一套持久化。

## Runtime 与可观测性边界 (Runtime And Observability Boundary)

BENE 是 runtime 本身。KAOS 则是围绕这个 runtime 提供的可观测层。在设计集成方案或编写文档时，请务必保持这条界线足够清晰。

BENE 掌握着执行权和持久化状态：agent 身份、VFS 文件、checkpoints、tool-call 记录、记忆体 (engrams)、跨局 memory、技能库 (skills)、Shared-log 决策、探针 (probes)、信任分 (trust) 以及晋升门禁 (promotion gates)。任何对 agent 工作状态的改变，都必须通过 BENE 的 API、CLI 或 MCP server 进入，以此确保底层的 SQLite runtime 永远是绝对的单一事实来源 (source of truth)。

KAOS 从这条边界之外进行观测、报警和推敲 (nudge)。它可以去抓取 tmux 屏幕、汇总 agent 状态、探测停滞的会话、监控日志并报告漏洞，但它绝不能演变成第二套 runtime、隐匿的状态仓库或者另外一条晋升通道。如果 KAOS 发现了某种必须被保留下来的事实，请通过 BENE 的 memory、engrams、shared log 或 issue 将其写入 BENE。

运作铁律非常简单：

```text
BENE = 运行环境、状态管理、门禁拦截、历史回放
KAOS = 外部观测、监控系统、保姆机制、偏差侦测
```

这种分离保证了 BENE 永远是可复现的 (reproducible)，而 KAOS 永远是可替代的 (replaceable)。即使 KAOS 宕机离线，任意一次执行也理应能仅靠 `bene.db` 还原；同时，任何一次 KAOS 警报，都必须能指向一条可验证底层状态的 BENE 命令或记录。

---

## VFS 引擎 (VFS Engine)

当你想知道 agent 到底写了什么、它看到的是哪个版本的文件，或者需要回滚到哪个 checkpoint 才能救场时，调用 VFS 引擎。它在 SQLite 之上提供了一套完整的文件、KV state、tool-call 跟踪以及 checkpoint/恢复 机制。

### SQLite 核心配置

```python
conn.execute("PRAGMA journal_mode=WAL")    # 预写式日志
conn.execute("PRAGMA foreign_keys=ON")      # 引用完整性
conn.execute("PRAGMA busy_timeout=30000")   # 遭遇锁争用时重试30秒
conn.execute("PRAGMA wal_autocheckpoint=100")
```

这几条 pragma 构成了数据库的契约：WAL 模式应对海量读操作并发，foreign keys 守住关系边界，30秒重试窗口消化数据库写入时的锁竞争。

### 线程安全 (Thread Safety)

通过 `threading.local()` 为每个 worker 线程独立分配一个 SQLite 连接。这既遵循了 SQLite 的连接池管理铁律，又使得各个独立的 agent 循环能够并行狂奔。

```python
class Bene:
    def __init__(self, db_path: str = "bene.db", compression: str = "zstd"):
        self._local = threading.local()
        # 每个线程通过 _get_conn() 拿自己的连接
```

### 内容寻址的 Blob 存储

`bene/blobs.py` 依靠 SHA-256 哈希值来落盘文件字节。不同 agent 写入的相同内容会被自动去重；`ref_count` 负责追踪活体引用；`store()` 执行压缩并写入，`retrieve()` 执行解压并吐出数据；默认以等级 3 运行 zstd 压缩；最后，`gc()` 会清理掉 `ref_count <= 0` 的废弃 blob。

```text
文件写入流：

   内容字节
        |
        v
   计算 SHA-256 -----> 去 blobs 表查是否存在?
        |                    |            |
        |                   存在         不存在
        |                    |            |
        |              ref_count += 1   压缩 (zstd)
        |                    |            |
        |                    |        INSERT blob
        |                    |            |
        +--------------------+------------+
        |
        v
   INSERT 到 files 表
   (agent_id, path, content_hash, size, version)
```

### 版本化文件系统

只要有文件写入，系统就会切出一个新版本。覆盖同一路径实际上是软删除（`deleted = 1`）旧的行数据而不抹掉实体，这不仅保留了该文件的变更历史，还给 checkpoint 的回溯留了底。`file_history(agent_id, path)` 可以抽出整个版本链。文件路径统一经 `PurePosixPath` 规格化，只要向某目录里塞了嵌套文件，父目录就会顺带自动创建。

### 事件日志 (Event Journal)

`bene/events.py` 是一条不可变 (append-only) 的流，完整记录生命周期、文件系统变动、状态更改、tool 执行、checkpoint 落地、警告甚至错误事件。这串流水可以用 agent、`event_type`、时间范围以及游标做筛选。

| Event Type 事件类型 | 触发时机 |
|---|---|
| `agent_spawn` | Agent 诞生 |
| `agent_pause` / `agent_resume` | 生命周期转换 |
| `agent_kill` / `agent_complete` / `agent_fail` | 生命周期终结 |
| `file_read` / `file_write` / `file_delete` | 文件系统动作 |
| `state_change` | KV 状态变化 |
| `tool_call_start` / `tool_call_end` | 工具执行起止边界 |
| `checkpoint_create` / `checkpoint_restore` | Checkpoint 动作 |
| `error` / `warning` | 运行时诊断抛出的异常 |

每条记录都有一个全局排序的 `event_id`，一个发起操作的 `agent_id`，一个事件类型标识，携带具体数据的 JSON payload，以及带毫秒级精度的 ISO 8601 时间戳。

### Checkpoint / 状态恢复

`bene/checkpoints.py` 的 checkpoint 一次打包锁定三样东西：当前有效的文件清单快照 `(path, content_hash, version)`，该 agent 下的所有 KV 状态，以及当前时间节点对应的事件水位线 (event watermark)。恢复 (Restore) 动作则首先软删除现存的所有文件，再把清单里的文件拉回来或者解除软删除，然后用状态快照去覆盖该 agent 现在的状态。对两个不同的 checkpoint 执行 diff，即可抽出两次事件水位线之间的所有文件变更、状态更迭以及产生的 tool calls。

---

## 隔离模型 (Isolation Model)

BENE 的隔离级别从数据库特性起步，如果跑在 Linux 上甚至能上升到系统进程级别。默认情况下运行的是逻辑隔离 (Logical isolation)；如果环境支持挂载和 cgroup，`bene/isolation.py` 还可以调动 FUSE 将其实体化。

### Tier 1 -- 逻辑隔离 (默认)

逻辑隔离通过将每一个 VFS 动作牢牢绑定在单一 `agent_id` 下面发挥作用。`LogicalIsolation` 把 `Bene` 给包装起来，调用者在每次调方法时甚至都不用显式传 agent ID，系统在下头就帮你卡死边界了。

```python
class LogicalIsolation:
    def read(self, path: str) -> bytes:
        return self.afs.read(self.agent_id, path)  # 边界已框死
```

这个层级的隔离零额外运行时开销，通吃 Windows、macOS 和 Linux，它完全依靠类似 `WHERE agent_id = ?` 的 SQL 判断将各个命名空间锁死。

### Tier 2 -- FUSE + 命名空间隔离 (仅限 Linux)

如果进程的确需要一种普通的文件系统视角，`IsolatedAgentProcess` 可以直接把 agent VFS 挂载到 `/tmp/bene/<agent_id>`，用 `unshare` 把进程扔进自己的 Linux mount 命名空间，并能顺手利用 cgroups v2 扣上诸如 `memory.max` 和 `cpu.weight` 之类的配额枷锁。

```text
Tier 2 隔离栈：

  +-------------------+
  | Agent 进程         |
  +-------------------+
  | Mount 命名空间     |  <-- unshare(CLONE_NEWNS)
  +-------------------+
  | FUSE 挂载点        |  <-- /tmp/bene/<agent_id>
  +-------------------+
  | Bene VFS 引擎      |
  +-------------------+
  | SQLite WAL        |
  +-------------------+
  | cgroups v2        |  <-- memory.max, cpu.weight
  +-------------------+
```

**触发前置条件：**

- 必须是 Linux (`platform.system() == "Linux"`)。
- 需安装 `fusepy` 依赖库 —— `pip install bene` 然后执行 `uv sync --extra fuse` 激活 FUSE 能力。
- 执行该命令的用户须具有 root 权限或对应的命名空间/cgroup 操作权限。

### 隔离工厂类

`create_isolation()` 负责根据配置文件拍板决定用哪一层的隔离：

```python
isolation = create_isolation(afs, agent_id, config)
# 产出 LogicalIsolation 或者是 IsolatedAgentProcess
```

---

## CCR 执行循环 (CCR Execution Loop)

位于 `bene/ccr/runner.py` 的 Claude Code Runner 承载着长寿命的 agent 执行循环。它把任务包装成 system prompt，把模型请求交给 Tier 路由器分发，直接执行需要执行的工具操作，把每一次观察打进存储层，并周期性 checkpoint 切片。

### 循环架构 (Loop Architecture)

```text
                  +------------------+
                  |   Task (prompt)  |
                  +--------+---------+
                           |
                           v
              +------------------------+
              | 构建 System Prompt     |
              | (融合 agent context与  |
              |   工具声明)           |
              +----------+-------------+
                         |
            +============+============+
            |     核心 CCR 循环        |
            | (受限至 max_iterations)  |
            |                         |
            |  +-------------------+  |
            |  |  1. 规划 (PLAN)   |  |
            |  |  经 Tier 路由     |  |
            |  |  获取模型回复      |  |
            |  +---------+---------+  |
            |            |            |
            |            v            |
            |  +-------------------+  |
            |  |  2. 执行 (ACT)    |  |
            |  |  执行 tool calls  |  |
            |  |  (如有)           |  |
            |  +---------+---------+  |
            |            |            |
            |            v            |
            |  +-------------------+  |
            |  |  3. 观察 (OBSERVE)|  |
            |  |  把结果追加进回话 |  |
            |  |  检查结束标识     |  |
            |  +---------+---------+  |
            |            |            |
            |   [未结? 进入下轮循环] |
            +============+============+
                         |
                         v
                  +--------------+
                  |    结果       |
                  +--------------+
```

### 步进拆解

1. 首先把 agent 状态拧成 `running`，从自身身份标识、可用工具以及具体的任务文本拼出 system prompt，最后把初始化的对话上下文记录在 agent 状态中。
2. 规划层 (Plan) 把对话推给 Tier 路由器，路由将其归类并分派对应的 vLLM 模型。
3. 执行层 (Act) 依据模型指令通过 `ToolRegistry` 执行，状态流从 `pending` 过渡到 `running`，最后将结果 `success`/`error` 记录进 `tool_calls`。
4. 观察层 (Observe) 把拿到的结果作为一环拼合回会话历史，累加迭代次数和心跳，倘若模型直接扔出不带工具调用的 `end_turn` 则终止循环。
5. 自动 checkpoint 每经过 `checkpoint_interval`（默认10）个迭代回合就会切出一张快照。

### 终止条件

正常结束、遭遇 `timeout_seconds`、耗尽 `max_iterations`，以及迭代间歇期间查实其处于 `killed` 状态或者因为 `paused` 状态陷入等待恢复唤醒的休眠。

### 并发执行能力

`ClaudeCodeRunner.run_parallel()` 用 `asyncio.gather()` 和一个容量信号量来并发推举 agent。默认 `max_parallel_agents` 阈值卡在 8。

### 工具登记处 (Tool Registry)

`bene/ccr/tools.py` 统管所有内置和定制的工具定义。所有 `fs_` 和 `state_` 开头的内建工具都能默认拿到活跃的 `agent_id` 以框定命名空间内的操作范围。下面列出核心 `fs_`/`state_`/`shell` 工具集；在部分内部部署中，`tools.py` 还能直接搭载一个翻译内部 Jira URL 为 NFS 存储挂载路径的 `squirrel_localpath`。

| Tool (工具) | 功能描述 |
|---|---|
| `fs_read` | 从该 agent VFS 读文件 |
| `fs_write` | 向文件写内容 |
| `fs_ls` | 列出目录成分 |
| `fs_delete` | 删除一个文件 |
| `fs_mkdir` | 新建目录 |
| `state_get` | 读取 KV 状态值 |
| `state_set` | 设定 KV 状态值 |
| `shell_exec` | 开个 shell 跑命令 (带超时) |

直接调用 `ccr.register_tool(ToolDefinition(...))` 就能添加客制化的工具。

---

## Tier 路由器 (Tier Router)

`bene/router/tier.py` 中的 Tier 路由器就是模型分发层。它会给每一个进来的推理请求贴上 `trivial`、`moderate`、`complex` 或 `critical` 标签，对应派单至不同段位的模型组，必要时对 context 发动缩骨功，要是调用崩了还会启动退场补救（fallback）。

### 架构透视

```text
   入站请求
  (messages, tools)
        |
        v
  +-------------------+
  |    分类任务        |
  |                    |
  |  +--------------+  |
  |  | 依靠LLM的    |  |  (首选，走 classifier_model)
  |  | 分类器        |  |
  |  +------+-------+  |
  |         |          |
  |    [遭遇失败时]     |
  |         |          |
  |  +------v-------+  |
  |  | 启发式        |  |  (回退防线，走正则+计分)
  |  | 分类器        |  |
  |  +--------------+  |
  +--------+-----------+
           |
           v
  分类裁决结果
  (trivial | moderate | complex | critical)
           |
           v
  +-------------------+
  | 路由表             |
  | trivial   -> 7B    |
  | moderate  -> 32B   |
  | complex   -> 70B   |
  | critical  -> 70B   |
  +--------+----------+
           |
           v
  +-------------------+
  | Context压缩器      |
  | (如有启用)         |
  +--------+----------+
           |
           v
  +-------------------+
  |   VLLMClient      |
  |   (原生 httpx)    |
  |   POST /v1/chat/  |
  |   completions     |
  +-------------------+
```

Tier 实打实是个原生支持 vLLM 的级联（cascade）路由器。这里的每一个内部零件，它的设计都有据可查，直接脱胎于某篇已发表的核心论文 —— 请翻阅本节最末的 [论文血统考 (Research Lineage)](#论文血统考-research-lineage)。直言不讳点出技术渊源，而不将其包装成某个玄学的自创术语，就是要让后面的工程师在需要翻新某个部件时，能有迹可循顺着家族树直接切出最新的论文。

### 任务定级 (Task Classification)

`bene/router/classifier.py` 里的 `LLMClassifier` 会向类似于 `qwen2.5-coder-7b` 的微型模型扔一段温度设在 0 绝对冷静的判定 prompt。模型应当仅吐出 `trivial / moderate / complex / critical` 其中之一。即使夹了点废话或大写，正则也能把它摘出来；这步要是扑街了，直接掉头去找启发式分类器救场。LLM 决策这一路，给出的置信度 (confidence) 被钉死在 0.85。

这种玩法 —— 让温度为 0 的微型模型充当判定探头去指挥路由，正是继承了 RouteLLM 论文中描述的 `causal_llm` 变体（[Ong et al. 2024](https://arxiv.org/abs/2406.18665)）。

同在 `bene/router/classifier.py` 的 `HeuristicClassifier` 采用三段式正则评分：

- `COMPLEX_PATTERNS`：诸如重构、架构设计、安全审计、迁移、分布式等重型词，每个命中记 +3.0 分。
- `MODERATE_PATTERNS`：编写、建函数、搞测试、修 bug 等活计，命中记 +1.5 分。
- `TRIVIAL_PATTERNS`：排版、改名、标注释、修笔误、导依赖等杂务，每个倒扣 -1.0 分。

它还会对堆了 50K 字符上下的上下文叠加 +2.0 分，超过 20K 叠加 +1.0，工具总数如果冲上 11+ 加 +1.0，对冗长的任务说明段则视字数加权（>500 字符加 +1.0，>200 加 +0.5）。综合裁定：总分 >= 5.0 划归 critical，>= 3.0 划归 complex，>= 1.0 归为 moderate，再低于这个门槛统统按 trivial 处置。置信度被框定为 `min(0.9, 0.5 + |score| * 0.1)`。

### 路由表挂载 (Routing Table)

整张路况表全都寄存在 `bene.yaml` 配置的各个模型 `use_for` 参数里：

```yaml
models:
  qwen2.5-coder-7b:
    use_for: [trivial, code_completion]
  qwen2.5-coder-32b:
    use_for: [moderate, code_generation]
  deepseek-r1-70b:
    use_for: [complex, critical, planning]
```

遇到尚未圈定的复杂度，直接甩给 `fallback_model` 兜底。如果在 agent 级别硬性指明了 `force_model`，一切分类裁决一概免除。

这种基于离散区间的层级调度，比连续打分的黑盒模型在逻辑上更逼近 AutoMix ([Aggarwal, Madaan et al. 2023](https://arxiv.org/abs/2310.12963)) 与 Hybrid LLM ([Ding et al. 2024](https://arxiv.org/abs/2404.14618)) 的核心思想。其中，Hybrid LLM 是这套双档变体的直系机理鼻祖；Tier 只不过是将这种 2 档位路由拓展成了 4 档。

### Context 上下文折叠 (Context Compression)

`bene/router/context.py` 的 `ContextCompressor` 按照大致 1个 token 顶 4个英文字符来粗估体量。它直接对超长 tool 输出下狠手：超出 2000 字符的一律剁掉中段，仅保留头 1000 与尾 500 个字符，中间接上一段 `[truncated]`（数据已截断）标记。接着在保留头端系统指令和末端最后 8 条消息 (`PRESERVE_RECENT`) 不动摇的前提下，把中间堆积的一大坨陈年旧账提纯汇总；若最后仍不满足选定模型 `max_context` 容量的 85%，那就对中间部分继续抽血压缩。

这种 "头尾原封保留，把夹心的旧历史挤压成附体指令重新贴回系统 message" 的折叠手段，发端于 MemGPT ([Packer et al. 2023](https://arxiv.org/abs/2310.08560)) 和 *Recursively Summarizing Enables Long-Term Dialogue Memory in LLMs* ([Wang et al. 2023](https://arxiv.org/abs/2308.15022))。目前的工程实现则严格向 Anthropic 产品化落地版本的 `/compact` 手法看齐（对应的 Claude API 参数就是 `compact-2026-01-12`）。

### vLLM 发射器 (vLLM Client)

`bene/router/vllm_client.py` 仅仅是一段短小精悍的异步 HTTP client，拒绝裹入任何厚重的外部 SDK。它仅仅在需要呼叫时才拉起 `httpx.AsyncClient` 执行 `POST {base_url}/chat/completions`，把与 OpenAI 规格对齐的一堆参数 (`model`, `messages`, `temperature`, `max_tokens`, `tools`, `tool_choice`) 扔给端口。拿到原生 JSON 后原原本本填装进 `ChatCompletion`、`ChatChoice`、`ChatMessage` 还有 `Usage` 这套数据结构里去。最终开放一个 `close()` 提供回收接口，并且设了 120秒 的默认 timeout 阈值。

### 弹射与补救 (Retry and Fallback)

对于掉线的模型呼叫，路由器会启动不超过 `max_retries` 设定的拉锯战；默认是 1（即单发不补枪）。如果非后备模型一直调不通，后续会直接切成指定的 fallback 模型重新走单。

### 论文血统考 (Research Lineage)

| 子模块 | 最核心论文 | 考据短评 |
|---|---|---|
| 级联路由 (先用便宜的顶不住再上贵的) | *FrugalGPT*, Chen, Zaharia, Zou (Stanford 2023) — [arXiv:2305.05176](https://arxiv.org/abs/2305.05176) | LLM 级联祖师爷级论文。阶梯表就是 FrugalGPT "LLM cascade" 思想的最佳注脚。 |
| 基于难度评估的调度 | *Hybrid LLM*, Ding et al. (Microsoft 2024) — [arXiv:2404.14618](https://arxiv.org/abs/2404.14618) | Tier 直系血统宗家。Tier 将论文里的 2 层路由平滑展开为 4 层。 |
| 微缩 LLM 充当分类裁决首脑 | *RouteLLM* (`causal_llm` variant), Ong et al. (UC Berkeley + Anyscale + LMSYS, 2024) — [arXiv:2406.18665](https://arxiv.org/abs/2406.18665) | "由小模型吐出定级标签" 的机制脱胎于此。 |
| 多层级离散瀑布分类 | *AutoMix*, Aggarwal, Madaan et al. (CMU + Google 2023) — [arXiv:2310.12963](https://arxiv.org/abs/2310.12963) | 把连续难度区间砍成四个具象离散段位的最近参考。 |
| 滚轴式汇总上下文收拢 | *MemGPT*, Packer et al. (UC Berkeley 2023) — [arXiv:2310.08560](https://arxiv.org/abs/2310.08560), 以及 *Recursively Summarizing*, Wang et al. (CAS 2023) — [arXiv:2308.15022](https://arxiv.org/abs/2308.15022) | system-message 缝合历史旧账手法发端。本代码块属于 Anthropic `/compact` 落地版手法的复现。 |

> **针对之前命名的一点澄清**。该路由此前曾经取名为 *Tier* (全称所谓 "Generalized Execution Planning & Allocation")。这个缩写完全是后期生凑出来的，在以上任何直系血统论文中毫无踪迹，而且偏偏还和另一篇主攻 prompt 优化而跟路由八竿子打不着的叫 *Tier: Reflective Prompt Evolution Can Outperform Reinforcement Learning* ([Agrawal et al. 2025](https://arxiv.org/abs/2507.19457)) 论文撞名了。**Tier** 作为现名更精准地点出了系统到底在干嘛，也方便代码审读者顺藤摸瓜回溯正宗的技术出处。

---

## MCP Server 整合 (MCP Server Integration)

MCP Server 是 Claude Code 以及所有兼容 MCP 协议的系统跟 BENE 打交道的专属通道。它的底层逻辑是：把操作口子抛出去，但核心执行和存储依然必须烂在 `Bene` 和 `ClaudeCodeRunner` 的肚子里。

这个装载于 `bene/mcp/server.py` 的 MCP server 使用 `mcp` 原生 Python 包打造，开放双重传输模式：

- **stdio 标准输入输出**: 专门给 Claude Code 这种贴身肉搏的直连进程用。
- **SSE 通道**: 基于 Starlette + uvicorn，把 Server-Sent Events 套上 HTTP 推向外部网络。

这个服务把足足 37 个 tool，归进了 9 大范畴（生命周期管理、VFS文件读写、Checkpoints、信息检索、蜂群编排、Meta-Harness调校、Memory检索、Shared Log协议、Skills库）；并且上述所有接口，每一条都能不偏不倚地精准对应回 `Bene`、`ClaudeCodeRunner`、`MetaHarnessSearch` 乃至底下那个抗造的协作存储堆栈上。想抄全部的图谱底牌，请移步 [mcp-integration.md](mcp-integration.md)。

### Server 点火挂载

```python
from bene.mcp.server import init_server

mcp_server = init_server(afs, ccr)
# afs: 初始化完毕的 Bene 实例
# ccr: 初始化完毕的 ClaudeCodeRunner 实例
```

`init_server()` 接过实例后，便将这套由 `Bene` 与 `ClaudeCodeRunner` 共同缔造的核心参考指针，直接铺平到所有 tool 执行回调函数的底下。

---

## 设计哲学 (Design Philosophy)

下列这组刚性铁律，直接解释了这套 runtime 为什么最终长成这幅摸样。

### 单文件便携 (Single-file portability)

把所有的 agent 文件、私有状态、刀光剑影的 tool-call 记录、日志时间轴以及 checkpoints，全数砸进一个单纯的 `.db` 文件。所谓迁徙，那就是一句单纯到无聊的 `cp bene.db backup.db`；而你手边随便一把轻量级的 SQLite 小凿子，就能将这内部全盘剖析。

### 对 AI SDK 说不 (Zero AI SDK dependencies)

BENE 有意拉黑一切诸如 `openai`、`litellm` 以及 `dspy` 这类繁杂的套件依赖。vLLM 底层的分发动作，只是端端正正靠一个剥得精光的 `httpx`，直白地甩给能看懂 OpenAI 通信规范的 `/v1/chat/completions` API 去处理；斩断包袱，防止这些沉重的周边套件发生飘移并把这套朴素的整合方案拖进兼容性深渊。

### 默认就是隔离的 (Isolation by default)

所有的文件碰触和底层查询都在开头硬核挂载了一个 `agent_id` 的紧箍咒。这种隔绝机制不再是所谓的君子协定；如果某些数据真的不允许一个 agent 越界摸到，那它甚至连相应的 API 探测口子都直接被隐身掉。

### 审计账本坚如磐石 (Append-only auditability)

不管什么动作 —— 读书、画写、涂销、状态易帜、呼唤神龙般地切工具、下 checkpoint 的死钩子、从生到死的演替、亮起黄灯或抛出红灯错误，全盘追加刻进事件底座，永不抹灭。到头来就留存出一条时间轨迹的化石，随你回放翻看。

### 拼装才是正义 (Composition over inheritance)

`Bene` 攥死存储，不假于人；`ClaudeCodeRunner` 分派路由去使唤 `TierRouter`；哪怕 MCP 服务在最上层，也是规矩地指派它俩充当代理；彼此绝不因为一厢情愿去走什么子类扩展的邪路。任何一个部件，摘除了都是完整独立的存在。
