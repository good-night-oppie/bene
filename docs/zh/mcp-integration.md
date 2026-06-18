# BENE 作为 MCP 服务器

<a id="overview"></a>

只要将 BENE 跟 Claude Code 挂载一次，从那一刻起，你就可以直接用自然语言来驱动你的 agents —— 喊一个出来写测试，在动高风险手术前打个 checkpoint，一旦搞砸了立马无缝回滚，更能在不切断聊天上下文的情况下用 SQL 查个底朝天。

> **只需在 `settings.json` 里加一段配置，Claude Code 就能瞬间觉醒 37 个 BENE 专属 tool —— agents, 文件系统, checkpoints, SQL 直查, meta-harness 演化搜寻, 跨世代 memory, shared log 还有 skills。而这一切的肉身，全在这台机器的一个 SQLite 文件里。**

这些 tool 染指的所有数据，死死锁在你自己电脑的 `bene.db` 里。默认的 stdio 传输通道根本不会去开什么网络端口，并且 `agent_query` 在架构底层被硬锁成了只读状态 —— 敢发写指令直接吃一个 `PermissionError`。除非你刻意作死选了 SSE 通道并把服务暴露出去，否则绝对不会有一滴数据碰到网卡。

本页导览:

- [接入 Claude Code](#connect-claude-code)
- [如何直接拉起服务端](#run-the-server-directly)
- [更廉价的平替：JSON CLI](#the-cheaper-path-the-json-cli)
- [Tool 全阵列参考](#tool-reference)
- [现在就能跑的实战对话](#conversations-that-work-today)
- [CLI-First 这条路到底赚了什么](#what-the-cli-first-path-adds)

原版锚点映射: [Overview](#overview), [CLI Alternative](#cli-alternative), [Starting the MCP Server](#starting-the-mcp-server), [Claude Code Integration](#claude-code-integration), [Available Tools](#available-tools), [Example Conversation Flows](#example-conversation-flows).

引擎盖下：这套服务端代码盘踞在 `bene/mcp/server.py`，底层骑的是官方的 `mcp` Python 包。它把一个 `Bene` 实例外加一个 `ClaudeCodeRunner` 裹在一起，一口气往外放了涵盖 9 大矩阵的 37 个 tool：生命周期、VFS (虚拟文件系统)、Checkpoints、Query 直查、编排指挥、Meta-Harness 演化、Memory、Shared Log 和 Skills。任何一个遵循 [Model Context Protocol](https://modelcontextprotocol.io/) 规范的客户端连上来，都能拿到一模一样的重火力。

---

<a id="claude-code-integration"></a>

## 接入 Claude Code

### 注册服务端

把这段硬塞进 `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "bene": {
      "command": "bene",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

### 强行指认数据库和配置表

```json
{
  "mcpServers": {
    "bene": {
      "command": "bene",
      "args": [
        "serve",
        "--transport", "stdio",
        "--db", "/path/to/project/bene.db",
        "--config-file", "/path/to/project/bene.yaml"
      ]
    }
  }
}
```

### 拿着源码树直接用 uv 拉起

没装全局包？那就直接用 `uv run` 从源码树里硬起：

```json
{
  "mcpServers": {
    "bene": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/bene",
        "bene", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

### 验明正身

改完 settings 之后把 Claude Code 重启，直接怼脸问它：

> "What BENE tools are available?"

要是 37 个 tool 全吐出来了，就算接稳了。

---

<a id="starting-the-mcp-server"></a>

## 如何直接拉起服务端

底层备了两条通道。跑 **stdio** 时，MCP 客户端会把 `bene serve` 当成自己的子进程直接拽起来，一切交流走 stdin/stdout —— 这就是 Claude Code 的御用通道。要是切到 **SSE**，一台飙着 Server-Sent Events 的 Starlette/uvicorn HTTP 服务器就会拔地而起，专门伺候那些需要走网络来连接 BENE 的客户端。

### stdio (默认通道)

```bash
bene serve --transport stdio
```

MCP 的报文从 stdin 砸进来；从 stdout 吐回去；Claude Code 像个暴君一样包办了这个进程从生到死。

**带参数版本:**

```bash
bene serve \
  --transport stdio \
  --db ./bene.db \
  --config-file ./bene.yaml
```

### SSE (开启网络暴露)

```bash
bene serve --transport sse --host 127.0.0.1 --port 3100
```

这台 HTTP 服务器会给你开两个口子:

- `GET /sse` — MCP 客户端从这里推门进来建立事件流。
- `POST /messages` — MCP 客户端把报文往这里丢。

**带参数版本:**

```bash
bene serve \
  --transport sse \
  --host 0.0.0.0 \
  --port 3100 \
  --db ./bene.db \
  --config-file ./bene.yaml
```

### 环境变量

| 变量名 | 默认值 | 描述 |
|---|---|---|
| `BENE_DB` | `./bene.db` | 数据库的肉身路径 (会被 `--db` 参数当场覆盖)。 |
| `BENE_CONFIG` | `./bene.yaml` | 配置文件路径 (会被 `--config-file` 当场覆盖)。 |

### 没给 `bene.yaml`？照跑不误

当系统抓不到 `bene.yaml` 时，服务端会毫不犹豫地降级 fallback 到 `claude_code` provider (绑死 claude-sonnet-4-6)。哪怕在这种残缺状态下，文件管理、checkpoints、还有 SQL 直查统统都能照常运转 —— 因为它们根本不跟大模型打交道，完全不需要你搞定什么 vLLM 部署。

---

<a id="cli-alternative"></a>

## 更廉价的平替：JSON CLI

只要是个 BENE 的指令，就能硬吃 `--json` 参数。这意味着任何一只能调 shell 的 agent，都能直接用结构化的输出反向操控 BENE —— 去他的 MCP 客户端，去他的 schema 解析开销：

```bash
# 纯结构化 JSON 输出 —— 是个 agent 就能把这玩意拆个明白
bene --json ls
bene --json status <agent-id>
bene --json query "SELECT * FROM agents WHERE status='running'"
bene --json mh status <search-agent-id>

# 丢进后台 —— 哪怕爹死了它照样跑
bene mh search -b text_classify -n 10 --background
```

什么情况下你应该毫不犹豫地抓起 CLI 而不是 MCP？

- token 预算吃紧时 —— 用 shell 把指令踢出去，彻底省掉 MCP 庞大的 schema 解析开销。
- 一场拉锯战一样的搜寻任务，必须得活过主进程的重启。
- 你手头的 agent 框架压根就没学会说 MCP 这门外语。

---

<a id="available-tools"></a>

## Tool 全阵列参考

37 个 tool，全按你想干什么排好了队。下面这张长桌详细拆解了核心 workflow 的常用武器；至于被同一个 server 挂载出来的 memory、shared-log、skill 以及拆分得很细的 meta-harness 单步工具，全塞在底下的附加列表里了。

### 拉起和操纵 agents

#### agent_spawn

一声令下，直接在一个跟外面绝对物理隔离的虚拟文件系统里拉起一个 agent 并把任务拍给它。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `name` | string | 是 | 给这个 agent 的代号。 |
| `task` | string | 是 | 它要拿命去拼的任务描述。 |
| `config` | object | 否 | agent 配置文件 (模型, temperature 什么的)。默认: `{}`。 |

**Returns:** 打包好的 `agent_id` 和 `result` 的 JSON。

**Example:**

```json
{
  "name": "test-writer",
  "task": "Write unit tests for the authentication module",
  "config": {"force_model": "deepseek-r1-70b"}
}
```

**Response:**

```json
{
  "agent_id": "01HXY...",
  "result": "I've written 12 unit tests covering..."
}
```

#### agent_spawn_only

光把 agent 生出来但是先别让它动 —— 当你需要先往它的 VFS 里塞点粮草代码进去时，用这一手。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `name` | string | 是 | 给这个 agent 的代号。 |
| `config` | object | 否 | agent 配置文件。默认: `{}`。 |

**Returns:** `agent_id` 和 `status` 的 JSON。

**Example:**

```json
{
  "name": "code-analyzer"
}
```

**Response:**

```json
{
  "agent_id": "01HXY...",
  "status": "initialized"
}
```

#### agent_parallel

一口气撒出去一票 agent 并行干活，然后坐收全部结果。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `tasks` | array | 是 | task 对象数组，每个都要带 `name` (string, 必填)、`prompt` (string, 必填)，以及可选的 `config` (object)。 |

**Returns:** 一份按顺序排好的结果 JSON 数组。

**Example:**

```json
{
  "tasks": [
    {"name": "test-writer", "prompt": "Write unit tests for payments"},
    {"name": "doc-writer", "prompt": "Update payment API documentation"},
    {"name": "refactorer", "prompt": "Refactor payments to use Stripe v3", "config": {"force_model": "deepseek-r1-70b"}}
  ]
}
```

**Response:**

```json
[
  {"index": 0, "result": "I've written 8 test cases covering..."},
  {"index": 1, "result": "Updated the API docs with..."},
  {"index": 2, "result": "Refactored the payments module to..."}
]
```

#### agent_status

单拎一个 agent 出来查成分 —— 或者直接留空，让它们排队点名。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 否 | Agent ID。留空则返回全员名单。 |
| `status_filter` | string | 否 | 状态过滤器 (`running`, `completed`, `failed` 等)。 |

**Returns:** 查单个就是个 JSON 对象；查全部就是一个 JSON 数组。

**Example — 查单个:**

```json
{
  "agent_id": "01HXY..."
}
```

**Response:**

```json
{
  "agent_id": "01HXY...",
  "name": "test-writer",
  "parent_id": null,
  "created_at": "2026-03-30T10:00:00.000",
  "status": "completed",
  "config": {"force_model": "deepseek-r1-70b"},
  "metadata": {},
  "pid": 12345,
  "last_heartbeat": "2026-03-30T10:05:00.000"
}
```

**Example — 抓取全场活人:**

```json
{
  "status_filter": "running"
}
```

#### agent_pause

当场冻结一个活着的 agent；回头用 `agent_resume` 再给它解冻。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | 待冻结的 Agent ID。 |

**Returns:** 一句确认回执。

#### agent_resume

解冻。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | 待解冻的 Agent ID。 |

**Returns:** 一句确认回执。

#### agent_kill

直接对一个活着的 agent 执行死刑。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | 待处决的 Agent ID。 |

**Returns:** 一句确认回执。

**Example:**

```json
{
  "agent_id": "01HXY..."
}
```

**Response:**

```text
Agent 01HXY... killed
```

### 文件出入控制

#### agent_read

从某个 agent 的 VFS 里活生生把一份文件抽出来。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |
| `path` | string | 是 | 待读取的文件路径。 |

**Returns:** 文件的 UTF-8 文本死尸。

**Example:**

```json
{
  "agent_id": "01HXY...",
  "path": "/src/auth.py"
}
```

#### agent_write

强行把一份文件塞进某个 agent 的 VFS 里。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |
| `path` | string | 是 | 文件路径。 |
| `content` | string | 是 | 文件内容。 |

**Returns:** 一句带着字节开销的确认回执。

**Example:**

```json
{
  "agent_id": "01HXY...",
  "path": "/src/auth.py",
  "content": "def authenticate(user, password):\n    ..."
}
```

**Response:**

```text
Written 41 bytes to 01HXY...:/src/auth.py
```

#### agent_ls

把 agent 肚子里的某一层目录抖搂出来。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |
| `path` | string | 否 | 目录路径。默认: `/`。 |

**Returns:** JSON 数组；每一项死死咬住 path, name, is_dir, size, modified_at 还有 version。

**Example:**

```json
{
  "agent_id": "01HXY...",
  "path": "/src"
}
```

**Response:**

```json
[
  {"path": "/src/auth.py", "name": "auth.py", "is_dir": false, "size": 1234, "modified_at": "2026-03-30T10:00:00.000", "version": 2},
  {"path": "/src/utils", "name": "utils", "is_dir": true, "size": 0, "modified_at": "2026-03-30T09:55:00.000", "version": 1}
]
```

### 冻结与时空倒流

#### agent_checkpoint

把这个 agent 当前的文件系统和 KV 脑容量连皮带肉一起打个包。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |
| `label` | string | 否 | 给这个快照贴个标签 (可选)。 |

**Returns:** 带着崭新 checkpoint ID 的确认回执。

**Example:**

```json
{
  "agent_id": "01HXY...",
  "label": "pre-refactor"
}
```

**Response:**

```text
Checkpoint 01HABC... created for agent 01HXY...
```

#### agent_checkpoints

把一个 agent 留下的所有时空坐标系底裤翻出来。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |

**Returns:** JSON 数组；每个快照都死带着 `checkpoint_id`, `label`, `created_at`, `event_id`, 以及 `metadata`。

**Example:**

```json
{"agent_id": "01HXY..."}
```

**Response:**

```json
[
  {"checkpoint_id": "01HABC...", "label": "pre-refactor", "created_at": "2026-03-31T10:00:00.000", "event_id": 42, "metadata": {}},
  {"checkpoint_id": "01HDEF...", "label": "post-refactor", "created_at": "2026-03-31T10:15:00.000", "event_id": 87, "metadata": {}}
]
```

#### agent_restore

强行把一个 agent 拽回到你早早拍好快照的过去。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |
| `checkpoint_id` | string | 是 | 待复活的 Checkpoint ID。 |

**Returns:** 确认回执。

**Example:**

```json
{
  "agent_id": "01HXY...",
  "checkpoint_id": "01HABC..."
}
```

**Response:**

```text
Agent 01HXY... restored to checkpoint 01HABC...
```

#### agent_diff

对比两个时空坐标之间究竟发生了什么畸变 —— 包括文件、KV 状态键，还有夹在中间的全部 tool call。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `agent_id` | string | 是 | Agent ID。 |
| `from_checkpoint` | string | 是 | 起点快照 ID。 |
| `to_checkpoint` | string | 是 | 终点快照 ID。 |

**Returns:** 一份把文件更替、状态变更还有中间的 tool calls 扒得干干净净的 JSON。

**Example:**

```json
{
  "agent_id": "01HXY...",
  "from_checkpoint": "01HABC...",
  "to_checkpoint": "01HDEF..."
}
```

**Response:**

```json
{
  "files": {
    "added": ["/src/new_module.py"],
    "removed": [],
    "modified": ["/src/auth.py"]
  },
  "state": {
    "added": {"new_key": "value"},
    "removed": {},
    "modified": {"iteration": {"from": 5, "to": 15}}
  },
  "tool_calls": [
    {"call_id": "...", "tool_name": "fs_write", "status": "success", "duration_ms": 12, "token_count": 500}
  ]
}
```

### 直接逼供数据库

#### agent_query

把 SQL 查询直插进 `bene.db` 的只读通道。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `sql` | string | 是 | SQL SELECT 查询语句。 |

**Returns:** 以 JSON 数组形式吐出来的结果集。

**Example:**

```json
{
  "sql": "SELECT name, status, created_at FROM agents ORDER BY created_at DESC LIMIT 5"
}
```

**Response:**

```json
[
  {"name": "test-writer", "status": "completed", "created_at": "2026-03-30T10:00:00.000"},
  {"name": "refactorer", "status": "running", "created_at": "2026-03-30T09:55:00.000"}
]
```

**Note:** 这是纯天然的只读口。只有 SELECT 能进，你想混进 INSERT, UPDATE, DELETE, DROP, ALTER, 或者是 CREATE？等着吃 `PermissionError` 吧。

### 繁育更强悍的 Harness

#### mh_search

踹起一脚 Meta-Harness 搜寻引擎：初代 harness 种子会被丢进 benchmark 靶场打分，接着每一轮迭代都会利用完整的执行 trace 去提炼改进点并提出新的变异提案。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `benchmark` | string | 是 | Benchmark 靶场名: `text_classify`, `math_rag`, `agentic_coding`，或是你随便捏的自定义 benchmark。 |
| `max_iterations` | integer | 否 | 搜寻轮次数。默认: 10。 |
| `candidates_per_iteration` | integer | 否 | 每轮提几个新提案出来卷。默认: 2。 |
| `config` | object | 否 | 用来强行覆盖 SearchConfig 的配置。 |

**Returns:** 带有 `status`, `pid`, `log_path` 还有 `message` 的 JSON。

**Example:**

```json
{"benchmark": "text_classify", "max_iterations": 10, "candidates_per_iteration": 2}
```

#### mh_frontier

等搜寻收官，直接把帕累托前沿 (Pareto frontier) 给拽下来。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `search_agent_id` | string | 是 | 跑 `mh_search` 拿到的那个 search agent ID。 |

**Returns:** 满载着 harness IDs、打分、轮次的帕累托前沿 JSON。

#### mh_resume

从一趟意外中断的搜寻中抓出最后那个打完收工的轮次，然后就地复活接茬跑。没有任何一滴心血会白流：之前的 harness 评估记录、traces，以及前沿状态都会无损继承；连 benchmark 靶场名、轮次提案数以及目标设定都会丝毫不差地接管过来。

**Parameters:**

| 字段 | 类型 | 是否必填 | 描述 |
|---|---|---|---|
| `search_agent_id` | string | 是 | 那个遭遇不测中断的 search agent ID。 |
| `benchmark` | string | 是 | 这个 search 当初发家的 benchmark (`text_classify`, `math_rag`, 或 `agentic_coding`) —— worker 恢复打分时得认准这道门。 |

**Returns:** 带有 `search_agent_id`, `status`, `pid`, `log_path` 和 `message` 的 JSON。

**Example:**

```json
{
  "search_agent_id": "01HXY...",
  "benchmark": "text_classify"
}
```

**Response:**

```json
{
  "search_agent_id": "01HXY...",
  "status": "resuming",
  "pid": 12345,
  "log_path": "/path/to/bene-worker-12345.log",
  "message": "Resume worker launched (PID 12345). Log: /path/to/bene-worker-12345.log."
}
```

### 同一个 Server 吐出来的隐藏弹药库

除了上面铺开的核心 workflow 表单，这套 MCP 阵列里还藏着额外的 19 把单发手枪：

- Meta-Harness 步进特战队: `mh_start_search`, `mh_submit_candidate`, `mh_next_iteration`, `mh_write_skill`, `mh_spawn_coevolution`, `mh_hub_sync`
- Agent 记忆库: `agent_memory_write`, `agent_memory_search`, `agent_memory_read`
- Shared log 总线: `shared_log_intent`, `shared_log_vote`, `shared_log_decide`, `shared_log_append`, `shared_log_read`
- 经验沉淀 Skills: `skill_save`, `skill_search`, `skill_apply`, `skill_list`, `skill_outcome`

想核对当前仓库里的真枪实弹？拿这把尺子量：

```bash
uv run python - <<'PY'
import asyncio
from bene.mcp.server import list_tools
async def main():
    tools = await list_tools()
    print(len(tools))
    print("\n".join(t.name for t in tools))
asyncio.run(main())
PY
```

---

<a id="example-conversation-flows"></a>

## 现在就能跑的实战对话

九段行云流水的端到端交火实录。排列顺序完全依着最真实的作战逻辑：拉起、撒网、微操、侦查、反悔、终极进化。

### 丢个 Agent 出去把测试填满

**You:** "Spin up a BENE agent to cover my auth module with unit tests."

**Claude Code 抬手就是一记:** `agent_spawn`

```json
{"name": "auth-tester", "task": "Write comprehensive unit tests for the authentication module covering login, logout, token refresh, and edge cases."}
```

**Claude Code 抓取回执:** 名为 `auth-tester` 的 agent (ID: 01HXY...) 产出了 15 个 unit test，并且反手给你吐了一段测试覆盖率摘要。

### 先塞粮草，后动刀子

**You:** "I want an agent loaded with code I already have — the refactor comes after."

**Claude Code 开始只生不养:** `agent_spawn_only`

```json
{"name": "refactorer"}
```

**Claude Code 开始硬塞代码:** `agent_write`

```json
{"agent_id": "01HXY...", "path": "/src/payments.py", "content": "def charge(amount): ..."}
```

**Claude Code 继续塞:** `agent_write`

```json
{"agent_id": "01HXY...", "path": "/tests/test_payments.py", "content": "def test_charge(): ..."}
```

**Claude Code 直接打好止血绷带:** `agent_checkpoint`

```json
{"agent_id": "01HXY...", "label": "before-refactor"}
```

**You:** "Now let it refactor."

**Claude Code 这才下发攻击指令:** `agent_spawn`，顺带着发了一个直接去啃刚才塞进去的那些文件的新鲜任务。

### 拉起四面夹击的火力网审代码

**You:** "Give me four reviews of this code in parallel — security, performance, style, test coverage."

**Claude Code 撒出一把豆子:** `agent_parallel`

```json
{
  "tasks": [
    {"name": "security-reviewer", "prompt": "Review this code for security vulnerabilities: ...", "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "performance-reviewer", "prompt": "Review this code for performance issues: ..."},
    {"name": "style-reviewer", "prompt": "Review this code for style and best practices: ..."},
    {"name": "test-reviewer", "prompt": "Suggest test cases needed for this code: ..."}
  ]
}
```

**四面八方的战报砸回来；Claude Code 当场揉成一份滴水不漏的总决议案。**

### 按下暂停键，扒拉完了再接着跑

**You:** "Hold the refactorer for a moment — I want to look over its progress."

**Claude Code 直接下冻结令:** `agent_pause`

```json
{"agent_id": "01HXY..."}
```

**You:** "Looks fine. Carry on."

**Claude Code 解除封印:** `agent_resume`

```json
{"agent_id": "01HXY..."}
```

### 把一个 agent 的老底掀个底朝天

**You:** "Walk me through everything the refactorer changed."

**Claude Code 直插数据库大动脉:** `agent_query`

```json
{"sql": "SELECT event_type, payload, timestamp FROM events WHERE agent_id = '01HXY...' ORDER BY event_id"}
```

**Claude Code 翻箱倒柜:** `agent_ls`

```json
{"agent_id": "01HXY...", "path": "/"}
```

**Claude Code 拉出文件尸首:** `agent_read`

```json
{"agent_id": "01HXY...", "path": "/src/payments.py"}
```

**然后 Claude Code 就跟解剖师一样，领着你把所有的事件流水和现在这坨文件的死状盘得清清楚楚。**

### 揪出当前战场所有的 token 吸血鬼

**You:** "Which agents are live right now, and what have they spent in tokens?"

**Claude Code 全场点名:** `agent_status`

```json
{"status_filter": "running"}
```

**Claude Code 强拉对账单:** `agent_query`

```json
{"sql": "SELECT a.name, SUM(tc.token_count) as tokens, COUNT(tc.call_id) as calls FROM agents a LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id WHERE a.status = 'running' GROUP BY a.agent_id"}
```

**Claude Code 把还在喘气的 agent 名单连带他们烧掉的账单重重地拍在你面前。**

### 一键抹除灾难级重构

**You:** "That refactor was a mistake. Take the agent back to the earlier checkpoint."

**Claude Code 去翻后悔药存根:** `agent_query`

```json
{"sql": "SELECT checkpoint_id, label, created_at FROM checkpoints WHERE agent_id = '01HXY...' ORDER BY created_at"}
```

**Claude Code 一眼咬住了那个贴着 "before-refactor" 标签的时空锚点。**

**Claude Code 拉动时间机器拉杆:** `agent_restore`

```json
{"agent_id": "01HXY...", "checkpoint_id": "01HABC..."}
```

**Claude Code 拉出时空裂隙对比单:** `agent_diff`

```json
{"agent_id": "01HXY...", "from_checkpoint": "01HABC...", "to_checkpoint": "01HDEF..."}
```

**Claude Code 平静地通报回滚战损:** 回到那重构前的时空，被改的 3 个文件和新加的 1 个文件（现已灰飞烟灭）—— 统统抹除干净，就当没发生过。

### 让 Meta-Harness 替你这只猴子去敲键盘

**You:** "Optimize my text-classification harness with a Meta-Harness search."

**Claude Code 一脚踹起进化池:** `mh_search`

```json
{"benchmark": "text_classify", "max_iterations": 10, "candidates_per_iteration": 2}
```

**进化前沿的战报糊脸:** 10 轮肉搏里足足卷了 23 套 harnesses；最高准确率杀到了 87% (harness 01HXY1F...)；性价比之王压到了 45 token 算一次 (harness 01HXY1G...)。

**You:** "Full frontier, please."

**Claude Code 把战利品端上来:** `mh_frontier`

```json
{"search_agent_id": "01HXY..."}
```

### 从死人堆里爬起来接着卷

**You:** "The search died at iteration 4 — pick it up where it stopped."

**Claude Code 直接给死人做电击复苏:** `mh_resume`

```json
{"search_agent_id": "01HXY...", "benchmark": "text_classify"}
```

**Claude Code 报告接续战况:** 从第 4 轮爬起来接力，一路杀穿 10 轮满贯，全场共卷 23 套 harnesses，天花板准确率 87% (harness 01HXY1F...)，帕累托前沿线上站着 4 套毕业装。

---

## CLI-First 这条路到底赚了什么

- **一切为了 CLI 优先。** 所有 command 都能咽下 `--json`，这说明哪怕一个再寒酸的 agent 也能直接扔一条 `bene --json ls` 的 shell 出去，而不用把海量的 MCP schemas 硬塞进它可怜的脑容量里 —— 光这一手就砍掉了巨大的单次调用 schema 解析税。
- **肥硕的数据尸体绝不弄脏网络通讯口。** 当一个 agent 吐出的垃圾话长过 4KB 时，真正的全尸会被悄悄沉到它的 VFS 里的 `/result.txt` 底下；而 MCP 通道上只挂着一小段预览和一个叫你去 `agent_read` 捞全尸的门牌号。
- **纯粹且具有洁癖的 JSON-RPC 事件流。** 在 stdio 通道刚苏醒的那一瞬，服务端直接把 `sys.stdout` 的导管暴力切到了 `sys.stderr` 上，这直接从物理隔离上保证了再也不会有哪个没教养第三方库乱拉日志污染这套神圣的协议。
- **搜寻任务能把活人熬死。** `mh_search` 和 `mh_resume` 是直接把活儿塞进脱缰在后台的 worker 进程嘴里；你哪怕把 MCP 的线给拔了也休想弄死它。这帮打工人会自己把日志吞吐到 `bene-worker-*.log` 里。
- **又有三条新指令加入了这支 CLI 大军:** `bene read`、`bene logs`，以及 `bene mh search --dry-run`。
