# BENE 命令行兵器谱 (CLI Reference)

从黑框终端里一键拉起、盯梢、回滚并拷问你的 agent 狼群 —— 且所有的命令，全都死死咬住同一个本地的 `bene.db` 数据库文件。

> **如果你是从源码跑的：** 刚跑完 `uv sync` 后，`bene` 这条命令是不会自动塞进你的 `PATH` 里的。所以，你要么在下面的每一条命令前面乖乖加上 `uv run` (比如 `uv run bene init`)，要么就老老实实 `source .venv/bin/activate` 一次激活环境，这样就能直接敲 `bene` 了。(当然，直接 `pip install bene` 也能解决烦恼。)

> **`--json` 是一面全局大旗 —— 请务必把它插在子命令的 *前面*** (`bene --json ls` 才是对的；要是写成 `bene ls --json`，系统会直接劈头盖脸骂你 `No such option`)。挂上这面大旗后，所有的输出都能直接塞给 `jq`、脚本流水线或者是隔壁的其他 agent 框架。(只要输出被管道接盘，就算你忘写这面旗，系统也会非常识相地自动吐 JSON。)

```bash
uv run bene --json <命令>
```

---

## 建营扎寨

### `bene setup`

一步到位的傻瓜向导：挑一个大模型预设，自动把 `bene.yaml` 给搓出来，顺手把数据库建好，最后再贴心地把 MCP server 强行注入进你的 Claude Code 里。

```bash
bene setup
```

你能在预设里挑：Claude (Sonnet), OpenAI (GPT-4o), 本地跑的 vLLM (7B/70B), 或者是你自己搭的野鸡 API 接口。

### `bene init`

开天辟地建库 —— 默认建在当前的 `./bene.db`，或者你指哪它建哪。

```bash
bene init
bene init --db ./my-project.db
```

### `bene demo`

一滴 API Key 都不用掏。第 1 阶段永远是先跑一段不烧 key 的极限极速 (<60秒) "内核大赏" —— engrams (记忆痕迹)、一条可证伪的探针 (probe)、跑一轮进化 (evolution)、然后收敛固化 (consolidation)、交出一份信任报告 (trust report) 以及感官清单 (senses manifest) —— 接着第 2 阶段会自动给 `demo.db` 塞点种子数据，并当场弹开你的浏览器切进仪表盘 (嫌烦可以用 `--no-ui` 憋回去)。

```bash
bene demo                # 看大赏，看仪表盘
bene demo --no-ui        # 纯看不烧 key 的大赏，跑完就退 (简直是 CI 的天作之合)
bene demo --port 9000
bene demo --no-browser
```

这壳子里到底装了啥：3 波接力执行的浪潮 —— 一群代码审查蜂群、一场并发重构战役、以及生产环境的工单急诊。

---

## 放狗咬人

### `bene run`

一句话，放出去一只 agent。

```bash
bene run "把 auth.py 统统重构成 JWT tokens" --name auth-agent
bene run "滚去找安全漏洞" --name security --db ./project.db
```

你能挂的旗:

- `--name`, `-n` — 给 agent 赐名 (敢不写试试)
- `--db` — 数据库路径 (默认: `./bene.db`)

### `bene parallel`

一声令下放出去一群 agent；每对 `-t 名字 "口令"` 就能多拉起一只。

```bash
bene parallel \
  -t security  "去 auth.py 里扒漏洞" \
  -t tests     "去给 auth.py 补单元测试" \
  -t docs      "去把 API 文档给更新了"
```

你能挂的旗:

- `-t name prompt` — 每个 agent 占坑一对 (可疯狂复读)
- `--db` — 咬住哪个数据库

---

## 现场盯梢

### `bene ui`

直接在浏览器里砸开一个仪表盘：有 Gantt 甘特图时间线、活蹦乱跳的事件信息流、以及能把你 agent 祖宗十八代都扒光的检查器。

```bash
bene ui
bene ui --port 9000
bene ui --db ./project.db --no-browser
```

想看更深的？去翻 [Dashboard 导读](dashboard.md)。

### `bene dashboard`

原汁原味的盯梢，只不过换成了极客狂喜的终端 TUI 界面。

```bash
bene dashboard
bene dashboard --db ./project.db
```

---

## 扒它的底裤

### `bene ls`

拉出所有的 agent 编制，连同它们的死活状态和生辰八字。

```bash
bene ls
bene ls --db ./project.db
bene --json ls | jq '.[] | select(.status == "failed")'
```

### `bene status`

把某一只 agent 扒个精光细看。

```bash
bene status <agent-id>
bene --json status <agent-id>
```

### `bene logs`

拉出这只 agent 跟大模型的对话记录，附带整条作案时间线。

```bash
bene logs <agent-id>
bene logs <agent-id> --tail 20    # 只瞄最后 20 条事记
```

### `bene read`

直接把手伸进 agent 的私有 VFS 领地里，把文件抽出来。

```bash
bene read <agent-id> /path/to/file
bene read <agent-id> /src/auth.py
```

### `bene failure localize`

追责神器：在一场翻车的战役里，精准揪出一切罪恶源头的那一案。它会生啃 agent 的 trace engrams (执行踪迹) —— 每次 `run_agent` 甩出一根线，每次 tool 跑完又留一笔案底 (包含 `tool_name`, `status`, `error_message`) —— 系统会拼出一条时间线，然后恶狠狠地指着那个引发雪崩的初始节点。

```bash
bene failure localize <agent-id>
bene failure localize <agent-id> --persist    # 把这次判案的结果死死刻进 tier-1 (第一层) 情景记忆里
bene --json failure localize <agent-id> | jq '.localized, .index'
```

这玩意**默认就能在真正的实盘上直接用** (不用 opt-in，也不用你人肉塞数据)，因为执行引擎本来就会无脑吐出那些带有报错案底的 trace engrams 供 `localize` 当罪证。如果之前那盘你手贱加了 `emit_engrams=False` / 或者是配了 `kernel.emit_engrams: false`，那对不起，没有案底可以啃，它只能摆摆手回一句 `localized: false`。

---

## 掘地三尺

### `bene search`

对着所有 agent 的文件和脑容量，发动降维打击级别的全文检索。

```bash
bene search "SQL injection"
bene search "ConnectionError" --db ./project.db
bene --json search "keyword" | jq '.[].path'
```

### `bene query`

直接拿裸 SQL 对着数据库狂轰滥炸 —— 这玩意安全到甚至可以直接甩给 agent 去玩。所有查水表的操作在 SQLite 引擎层就被上了锁 (`PRAGMA query_only`)，所以任何企图篡改历史的动作 —— `INSERT`/`UPDATE`/`DELETE`、带了 `WITH … DELETE` 的 CTE，哪怕是用注释伪装的恶意语句 —— 统统会在引擎底层被直接击毙，根本轮不到被那种能被绕开的正则表达式去拦截。谁敢越界，当场报 `PermissionError` 枪毙。

```bash
bene query "SELECT name, status FROM agents"
bene query "SELECT SUM(token_count) FROM tool_calls"
bene query "SELECT * FROM events WHERE agent_id = 'abc123' ORDER BY timestamp"
```

数据库里到底有哪些表？去翻 [核心血肉解剖图 (Schema)](schema.md)。

### `bene index`

强行给 agent 的 VFS 领地生成一份 `/index.md` 目录摘要，让后续的搜索快如闪电。

```bash
bene index <agent-id>
```

---

## 给我一颗后悔药

### `bene checkpoint`

把 agent 脑容量和名下所有的文件全盘冻结，并挂上一个标签。

```bash
bene checkpoint <agent-id> --label "before-migration"
bene checkpoint <agent-id> -l "pre-refactor"
```

### `bene checkpoints`

把这只 agent 裤兜里揣着的所有存根快照全抖搂出来。

```bash
bene checkpoints <agent-id>
bene --json checkpoints <agent-id>
```

### `bene diff`

把两次时空切片按在桌上对比 —— 哪些文件无中生有、哪些毁尸灭迹、哪些被动过手脚，连带记忆状态的篡改，一览无余。

```bash
bene diff <agent-id> --from <checkpoint-id-A> --to <checkpoint-id-B>
```

### `bene restore`

把时间强行倒推，让该 agent 在指定的快照点复活；且绝对不波及隔壁的其他 agent。

```bash
bene restore <agent-id> --checkpoint <checkpoint-id>
```

不知道 ID？用 `bene checkpoints <agent-id>` 去找。

---

## 停机，切片，跑路

### `bene kill`

一发子弹，干掉正在跑的 agent。

```bash
bene kill <agent-id>
```

### `bene export`

连锅端：把这只 agent 所有的身家性命单独打包成一个极致便携的数据库文件。

```bash
bene export <agent-id> --output agent-snapshot.db
```

### `bene import`

招魂：把导出的 agent 原封不动地请回来。

```bash
bene import agent-snapshot.db
```

---

## 怼进 Claude Code 肚子里

### `bene serve`

化身为拥兵 37 把专武的 MCP server，全裸暴露给 Claude Code —— 或者是任何 MCP 兼容的客户端。

```bash
bene serve --transport stdio       # 喂给 Claude Code / 以及绝大多数客户端的标配
bene serve --transport sse         # 走 HTTP/SSE 总线
bene serve --port 8765             # 换个端口玩 (仅限 SSE 模式)
```

想知道怎么装进去？翻翻 [MCP 植入指南](mcp-integration.md)。

---

## 给脚手架 (Harness) 配种催化

在终端里直接拉起 prompt 和策略全自动演化寻优的狂潮。

```bash
bene mh search -b <考卷名> -n <轮数>   # 鸣枪开战
bene mh search -b text_classify -n 10 -k 2      # 干 10 轮，每轮憋 2 个变种
bene mh search -b agentic_coding -n 20 --background   # 丢到后台自己卷
bene mh status <search-agent-id>                 # 盯梢战局
bene mh frontier <search-agent-id>               # 膜拜处于帕累托巅峰的变种
bene mh knowledge                                # 翻看战役里攒下来的千古绝活
bene mh resume <search-agent-id> -b <考卷名>  # 断线重连 (考卷名必须跟开局一致)
```

更多血腥细节，去翻 [演化脚手架 (Meta-Harness) 导读](meta-harness.md)。

---

## 哪都能插的通用大旗

| 大旗 | 到底是干嘛的 |
|---|---|
| `--json` | 强行逼迫输出成结构化 JSON (接了管道时会自动觉醒) |
| `--db PATH` | 咬死数据库文件 (默认: `$BENE_DB` 或者 `./bene.db`) |
| `--version` | 报上名号版本 |
| `--help` | 凡事不决直接敲 |

### 环境暗号 (环境变量)

| 暗号 | 默认值 | 到底是干嘛的 |
|---|---|---|
| `BENE_DB` | `./bene.db` | 默认的数据库归宿 |
| `BENE_CONFIG` | `./bene.yaml` | 配置文件该去哪找 |
