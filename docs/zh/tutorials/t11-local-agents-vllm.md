# 教程 t11 — 驾驭本地 vLLM 狼群：零成本、可全量审计的多 Agent 底座

*入门教程 · 耗时约 30 分钟*

---

教你把你手头那张吃灰的显卡压榨到极致，跑起具有全自动化能力的 BENE 特种兵，并且直接从 Claude Code 里去发号施令，最爽的是：不用给模型供应商交哪怕一分钱的 token 费。不出 30 分钟，你就能亲手搭出一个拥有 3 只特种兵背对背写代码的施工队、能体验一次沙盒级的读档重来，外加一套用纯 SQL 就能拷问出所有真相的审计系统。

> **这一整套系统的所有状态，全部浓缩在你硬盘上的一个 SQLite 文件里 —— `cp bene.db backup.db` 就等于完成了全库备份，没有任何一个字节会流出你的机器。**

> **走完这篇教程，你将喜提：**
>
> - 一个拿 vLLM 跑在你本地显卡上的 7B 大模型 (或者任何一个套着 OpenAI 兼容壳子的远端接口)。
> - 一套被你捏成了 Tier (梯队) 路由的 BENE 底座 —— 随你是单模型、多模型混合、还是本地+云端杂交。
> - 一个能跟 BENE 拿 MCP 协议愉快聊天的 Claude Code，而且 18 把 BENE 兵器全部实装。
> - 一只通过 Claude Code 亲手唤醒并跑到通关的 "hello world" 测试版 agent。
> - 3 只并发冲锋的特种兵 (写测试的 / 写实现的 / 写文档的) 体验极度隔离的 VFS，外加用 SQL 验证它们真的没串门。
> - 一次为了演示而故意弄砸的重构，外加一次极其丝滑的读档回滚 (rollback)。
> - 一本能被你用 `bene query` 或任何 SQLite 客户端拷问的 SQL 审计流水账。

Claude Code 这种外接神器直到第 4 步才会登场 —— 在那之前的活儿，光靠 bene CLI 自己就能干完，所以这篇教程的前半部分，其实也是一份纯命令行玩法的快速上手指南。

## 进场前的行囊

- 一台跑 Linux 或 macOS 的工作站。
- 一张 **显存 ≥16 GB** 的 GPU 用来伺候 7B 模型，或者 **≥48 GB** (插几张卡拼起来也行) 来伺候 70B 大爷。
- 装好 Python ≥3.10 以及 [`uv`](https://github.com/astral-sh/uv) 极速包管理器 (`curl -LsSf https://astral.sh/uv/install.sh | sh`)。
- 腾出大约 15 GB 硬盘空间 (模型的权重会被塞进 `~/.cache/huggingface/` 里)。
- 在本地装好 Claude Code —— 第 5 步往后才会用到。

> **没显卡怎么办？** 这篇教程里的所有调度、配置和审计招数你照样能玩 —— 只要把配置文件里的 `endpoint:` 指向任何一个兼容 OpenAI 格式的远端接口 (比如 Together, Anyscale, Fireworks, RunPod，甚至是别人机器上的 llama.cpp/ollama) 就行，假装没看见那些 vLLM 专属的黑话。

## Step 1 — 把模型端上来 (5 分钟，外加第一次拉权重的漫长等待)

下载模型是这篇教程里最熬人的环节，所以你最好现在就把它踢去后台跑。vLLM 暴露出来的接口跟 OpenAI 是一模一样的；BENE 是直接拿最底层的 `httpx` 去跟它裸聊的 —— 什么臃肿的 `openai` SDK、什么 `litellm` 胶水层，这套系统里压根就没有。

### 一张卡，一个模型 —— 最原教旨主义的跑法

```bash
pip install vllm
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
```

拿棍子戳它一下看看死活：

```bash
curl http://localhost:8000/v1/models
# 正常的话，它会吐一坨 JSON 出来，里面写着它挂着的模型名字。
```

> **实战套路。** 第一次拉起时它会把模型权重生拽到 `~/.cache/huggingface/` 里 (7B 模型大概要吃掉 14 GB)。如果你家网速不行，推荐先拿 `huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct` 在后台慢慢拉；一旦缓存热了，启动也就几秒钟的事。

### 阶级森严：三梯队模型伺候 —— 显存大户 (≥48 GB VRAM) 专享

```bash
# 终端 1 — 抓个小模型来应付脏活累活，兼职当路由器的分拣员
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000

# 终端 2 — 抓个中等个子的模型来扛起普通难度
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8001

# 终端 3 — 供一尊大佛，专解那种骨灰级难题
vllm serve deepseek-ai/DeepSeek-R1-70B --port 8002
```

> **顺藤摸瓜。** [教程/t06 — ML 炼丹实验室](t06-ml-research-lab.md) 就是拿这套极其奢华的 3 卡阵容，同时跑着 6 只科研 agent 熬了个通宵；你在第 3 步里要写的那个配置文件，其实就是从 t06 那边抄来的。

### 没 vLLM？只要长了个 `/v1/chat/completions` 的嘴，谁来都行

因为 BENE 客户端这边极其克制地只用了纯正的 httpx，所以服务器那边你随便换什么阿猫阿狗都行：

- **vLLM** (强烈推荐) — 打包推理 (batched inference) 速度最变态的怪物。
- **llama.cpp** / **ollama** — 极其下沉，家用破电脑都能跑。
- **text-generation-webui** — 如果你早就装了这破玩意，将就着用也行。
- **LocalAI** — 专门拿来假冒 OpenAI 的李鬼。
- 各种云端平替厂牌 — Together, Fireworks, Anyscale, RunPod, 等等。

把 `endpoint:` 指向那边的 URL 即可。

## Step 2 — 装配 bene (2 分钟)

把代码克隆下来后，顺手敲一发 `uv sync`，这能保证你本地的虚拟环境跟项目锁定的版本一模一样，免得出幺蛾子。

```bash
git clone https://github.com/good-night-oppie/bene.git
cd bene
uv sync
uv run bene --version
# bene, version 0.1.0
```

去捏一个数据库出来 —— 随你喜欢互动式向导还是纯手工打造：

```bash
# 懒人专用向导 — 挑个预设，自动生成 bene.yaml，外加把 DB 给你建好。
uv run bene setup

# 纯手工老炮 — 空白数据库，外加默认配置。
uv run bene init
# Initialized BENE database: ./bene.db
```

它的依赖列表被砍得极其短小精悍：`httpx`, `click`, `rich`, `textual`, `mcp`, `pyyaml`, `zstandard`, `ulid-py` —— 满打满算 44 个包，冷启动装完不到 30 秒，热启动只要各位数秒。这里绝对没有任何那种动不动上百兆的臃肿 AI SDK 全家桶。

> **实战套路。** `bene setup` 绝对是最快的捷径。它会帮你把 `bene.yaml` 糊好，顺便帮你把 `bene init` 敲了。选一个最对你胃口的预设板子：`local`, `local-multi`, `anthropic`, `openai`, 或者是 `hybrid`。

## Step 3 — 给 bene 指明模型的巢穴 (3 分钟)

刚刚已经用过 `bene setup` 了？那 `bene.yaml` 早就在那了 —— 直接跳到这一步最底下的那个连通性测试。如果你是手工老炮，先从样例文件抄一份：

```bash
cp bene.yaml.example bene.yaml
```

### 单机单模型

```yaml
database:
  path: ./bene.db
  wal_mode: true
  compression: zstd

models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]

router:
  fallback_model: qwen2.5-coder-7b
  context_compression: true

ccr:
  max_iterations: 50
  checkpoint_interval: 10
  max_parallel_agents: 4
```

### 梯队化多模型编队

```yaml
database:
  path: ./bene.db
  wal_mode: true
  compression: zstd

models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, code_completion]

  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for: [moderate, code_generation]

  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for: [complex, critical, planning]

router:
  classifier_model: qwen2.5-coder-7b   # 拿这个最廉价的 7B 去做难度分诊
  fallback_model: deepseek-r1-70b       # 把大佛当成最后的兜底防线
  context_compression: true

ccr:
  max_iterations: 100
  checkpoint_interval: 10
  max_parallel_agents: 8
```

来看看 Tier (梯队) 路由器在接到活时到底在背地里干了啥：

1. 它先去问 `classifier_model` (分诊员，也就是那个 7B)：这活大概是个什么难度？(trivial/无脑, moderate/中等, complex/复杂, critical/致命)。
2. 然后它去模型池里翻牌子，看看哪个模型的 `use_for` 名单里认领了这个难度标签。
3. 万一那个当分诊员的模型自己都脑梗了，系统会降级到纯靠关键字猜谜 (`refactor`, `security`, `format`, …)。
4. 万一接单的那个模型中途跑路报错了，这破摊子会直接丢给 `fallback_model` (兜底老大哥) 去擦屁股。

> **实战套路。** 分诊员唯一的职责就是贴标签，所以用 7B 绰绰有余，而且放在显存里热启动极快。那种 70B 的神仙算力，请省下来用在真正干活的地方，别拿它去问 "这活难不难？" 这种蠢问题。

### 本地+云端双修 (Hybrid)

把那些无脑的改名、调参脏活全甩给不花钱的本地 GPU；只有遇到真正值得烧钱的硬骨头时，才去请云端大模型出山。

```yaml
models:
  claude-sonnet:
    provider: anthropic
    model_id: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
    max_context: 200000
    use_for: [complex, critical]
  gpt-4o:
    provider: openai
    model_id: gpt-4o
    api_key_env: OPENAI_API_KEY
    max_context: 128000
    use_for: [moderate]
  local-qwen:
    provider: local
    endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial]

router:
  classifier_model: local-qwen
  fallback_model: claude-sonnet
  context_compression: true
```

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

> **实战套路。** 双修流最大的红利，就在于你代码库里那种纯粹靠堆人力的脏活极其多。如果你能把 80% 类似 "帮我把这堆变量名全改了" 的需求全塞给免费的本地模型，剩下的 20% 硬骨头丢给 Claude —— 你每个月的账单能被极其粗暴地砍掉这 80%。在瞎调参之前，请拿真实数据说话：Tier 路由器每次分诊的记录都会极其诚实地记在流水账里，你只需要去 `events` 表里跑一句 SQL，就能算出真实的拦截率，而不是你坐在电脑前凭空意淫出来的拦截率。

### 穷到底：纯云端

穷到连一张显卡都拿不出手？那就别管 vLLM 了：去挑个 `anthropic`, `openai`, 或者 `hybrid` 预设，把所有模型的端点全指向云服务商。

### 点把火试车

```bash
uv run bene run "给我打个招呼，然后把你能调用的那些破兵器全列出来看看" --name test-agent
```

只要你能看到 agent 极其规整地吐出结果，而且 `bene.db` 里冒出了一堆新鲜的记录，那就说明从模型到 bene 的这条血管已经打通了。在去折腾 MCP 之前，必须确保这步是顺畅的 —— 不然的话，两头同时查 bug 绝对会让你生不如死。

## Step 4 — 把指挥权移交给 Claude Code (3 分钟)

把 bene 伪装成一个 MCP 服务端挂载上去之后，Claude Code 就能直接使唤 bene 军火库里的那 18 把兵器。

### 挂载服务端

打开 `~/.claude/settings.json` (没这破文件就自己建一个)：

```json
{
  "mcpServers": {
    "bene": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/your/bene",
        "bene", "serve", "--transport", "stdio",
        "--config-file", "/path/to/your/bene/bene.yaml"
      ]
    }
  }
}
```

把 `/path/to/your/bene` 换成你当年 clone 下来那个仓库的真实路径。

如果你是暴发户装法 (`uv tool install .` 挂在了全局)：

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

### 清点 37 把兵器

把 Claude Code 关了重开，然后拷问它：

> *"BENE 都给你配了些什么杀器？(What BENE tools are available?)"*

它应该会如数家珍地给你报上这一长串名单：`agent_spawn`, `agent_spawn_only`, `agent_kill`, `agent_pause`, `agent_resume`, `agent_status`, `agent_read`, `agent_write`, `agent_ls`, `agent_checkpoint`, `agent_restore`, `agent_diff`, `agent_checkpoints`, `agent_query`, `agent_parallel`, `mh_search`, `mh_frontier`, `mh_resume`, `mh_start_search`, `mh_submit_candidate`, `mh_next_iteration`, `mh_write_skill`, `mh_spawn_coevolution`, `mh_hub_sync`, `agent_memory_write`, `agent_memory_search`, `agent_memory_read`, `shared_log_intent`, `shared_log_vote`, `shared_log_decide`, `shared_log_append`, `shared_log_read`, `skill_save`, `skill_search`, `skill_apply`, `skill_list`, `skill_outcome`。

> **排雷指南。** 如果 MCP 连不上，最暴力的排雷手段就是抛开 Claude，自己跑到命令行里干拉服务端：`uv run --project /path/to/bene bene serve --transport stdio`。如果能拉起来没报错，那绝逼是你的 `settings.json` 没写对 (八成是逗号漏了之类的 JSON 低级错误)。如果干拉都起不来，那就是 BENE 的问题或者是 `bene.yaml` 写残了。

## 来看看你刚刚拼出了一台什么神仙机器

```text
┌──────────────────────────────┐
│        Claude Code           │  ← 你的金口玉言全对它说 (第5步之后)
│  (你的黑窗口 / IDE 里)         │
└─────────┬────────────────────┘
          │ MCP 军用通讯协议 (stdio)
          ▼
┌──────────────────────────────┐
│       BENE MCP Server       │  ← 军火库 37 把兵器: 放狼(spawn), 读写,
│  agent_spawn, agent_parallel,│     拍快照(checkpoint), 拷问(query),
│  agent_checkpoint, mh_search │     叫停(pause), 搜寻(mh_search) 等等
└─────────┬────────────────────┘
          │
          ▼
┌──────────────────────────────┐
│       BENE core + CCR       │  ← 私人结界(VFS), 死亡日记(event journal),
│  SQLite, 二进制库, 事件引擎    │     快照存盘, 二进制去重黑科技
└─────────┬────────────────────┘
          │ 梯队路由 (原始粗暴的 httpx)
          ▼
┌──────────────────────────────┐
│           vLLM               │  ← 你家那张发烫的显卡
│  Qwen, DeepSeek, Llama, …    │     或者任何接 /v1/chat/completions 的口子
└──────────────────────────────┘
```

从上往下顺一遍：你在嘴上吹的牛逼，变成了 MCP 的刀光剑影；每一刀都稳稳地砍进了 bene core 里面，而 core 会给每一只出战的特种兵圈出一个带墙的 VFS 结界；梯队路由器给这活儿贴上难度标签，然后把它发包给某个最般配的模型；这个模型，其实就是在你显卡上跑着的那团肉块。每一次这套系统里发生了任何风吹草动，全都会被死死记进 SQLite 的流水账里，而且自始至终，绝没有任何一滴数据曾经溜出过你的网线。

> **顺藤摸瓜。** 去看 [教程/t00 — 端到端通关大纲](t00-bene-e2e-walkthrough.md)，那里演示了一套极度硬核的 `空降(spawn) → 拍快照(checkpoint) → 拷问(audit) → 逆转时空(restore)` 的闭环大戏，而且**连大模型都不需要开**。这绝对是热身的极品：你能极其干净地把 "审计库的玩法" 和 "大模型的间歇性发癫" 彻底剥离开来。

## Step 5 — 单狼出击，一条龙跑通 (2 分钟)

在 Claude Code 里面发号施令：

> *"用 BENE 放一只代号叫 'hello-world' 的特种兵出去，让它在 /src/main.py 里面用 Python 写个 hello world 的脚本出来。"*

你轻飘飘的一句话，在底下掀起了什么滔天巨浪：

1. 一记 `agent_spawn` 被轰了出去，包裹里揣着 `name="hello-world"` 和你那句原味的指令。
2. bene 极其熟练地划了一块处女地，给这只特种兵圈出了一个绝对隔离的 VFS 结界。
3. 梯队路由器看了一眼指令，打上了 "无脑 (trivial)" 标签，顺手就甩给了 7B。
4. 这只特种兵开始了它死循环般的一生 (计划 → 动手 → 看看行不行)：做决定，一记 `fs_write` 把字刻进 `/src/main.py`，看看有没有写歪，然后打卡下班。
5. 它的每一次抽搐，都被极其冷血地钉进了 `events` 表的日志里。

把战利品掏出来看看：

> *"从那个叫 hello-world 的特种兵结界里，把 /src/main.py 给我拿出来读一遍。"*

查它的流水账：

> *"给我把 hello-world 这个特种兵的一生，按时间线列出来看看。"*

Claude Code 反手就是一发 `agent_query` 砸进数据库：

```sql
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = '...' ORDER BY event_id;
```

这只特种兵这辈子干过的任何一点见不得人的勾当，在这里都无所遁形：被放出笼子 (`agent_spawn`)，动了文件 (`file_write`)，抄起了兵器 (`tool_call_start` 到 `tool_call_end`)，寿终正寝 (`agent_complete`)。

> **顺藤摸瓜。** [教程/t00 — 端到端通关大纲](t00-bene-e2e-walkthrough.md) 在没有大模型搅局的纯净环境里，把这套 `空降 → 读取 → 拷问` 的动作极其冰冷地走了一遍。这绝对能让你在被大模型那难以捉摸的回复绕晕之前，先摸透那个审计库的骨架到底长什么样。

## Step 6 — 多路齐进：三狼并排冲锋 (5 分钟)

在 Claude Code 里面发号施令：

> *"用 BENE 一口气放出 3 只特种兵，让它们分头同时跑:*
> *1. 代号 'test-writer' — 专门给支付系统的 REST 接口写单元测试。*
> *2. 代号 'implementer' — 专门去把那个支付接口的逻辑写出来。*
> *3. 代号 'doc-writer' — 专门给那个支付接口写 API 文档。"*

幕后的腥风血雨：

1. 一记巨大的 `agent_parallel` 把这 3 个任务包在同一个炸药包里扔了出去。
2. 三只特种兵被同时唤醒，每一只都待在只有自己的 VFS 结界里。
3. 路由器对每个任务进行独立分诊，并精准派发给相应的模型。
4. 三匹狼并排狂飙，速度极限取决于那个信号量阀门 (默认允许 8 只并排跑)。
5. 每跑满 10 个回合，系统极其冷血地强行按着它们的头存个盘 (checkpoint)。

### 算算这帮牲口各自吃了你多少算力

> *"这三只特种兵各自烧了我多少 token？"*

```sql
SELECT a.name, SUM(tc.token_count) AS tokens, COUNT(tc.call_id) AS calls
FROM agents a LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
GROUP BY a.agent_id ORDER BY tokens DESC;
```

### 谁背着你写了些什么破东西

> *"列出这几只特种兵到底往硬盘里塞了哪些文件。"*

```sql
SELECT a.name, f.path FROM files f
JOIN agents a ON f.agent_id = a.agent_id
WHERE f.deleted = 0 ORDER BY a.name, f.path;
```

看清楚在这场混战里 **没** 发生什么：写业务逻辑的和写测试的都往同一个名叫 `/src/payments.py` 或 `/tests/test_payments.py` 的路标上塞了东西，但是，没有任何人撞了任何人的车。每一条文件路径，只在那只特种兵自己的私有领域里生效 —— 这特么是底层的 SQL 结构强行焊死的铁律，而不是靠劝这帮大模型 "你们要讲武德，别动别人的文件" 求来的假象。

> **实战套路。** 系统默认的 `max_parallel_agents` 是 8。你要是想把这数往上拉，悠着点 —— 每一头在跑的狼，都在极其粗暴地吃着你显卡上的 KV 缓存空间。那种拿多张显卡拼在一起的 vLLM 倒是能靠张量并行 (tensor parallelism) 强行把这个天花板顶碎，代价是你每发一个请求的延迟会变得贼难看。

> **顺藤摸瓜。** [教程/t03 — 安全攻防特种部队](t03-security-swarm.md) 玩了完全一样的人格分裂套路，并极其霸道地用一条 SQL 证明了它们绝对没看过隔壁老王的卷子。把它当成 "物理隔离绝对不是吹水" 的实证来看。

### 全景视窗现场盯盘 (1 分钟)

```bash
uv run bene dashboard
```

一个用 Textual 糊出来的纯命令行看板，死死盯着每一匹狼的死活 —— 是在狂奔，是凯旋了，是阵亡了，还是被活活卡死了 —— 外加一个永远在滚动的事件流水账。当你在玩大兵团冲锋时，这玩意儿能保你一命，毕竟谁特么愿意在黑窗口里一次次狂敲 `SELECT` 刷新啊。

## Step 7 — 吃后悔药：快照、时光倒流与清算 (5 分钟)

### 实景演练：带着反悔机制的无损重构

> *"用 BENE 给我干这几件事：(1) 放一只代号 'refactorer' 的特种兵。 (2) 把这段代码写进 /src/auth.py 里：[贴代码]。 (3) 拍个快照，贴个标签叫 'original'。 (4) 叫它重构这段代码，把缺失的错误处理全加上。"*

假设它重构完的代码跟狗啃的一样：

> *"这破重构没法看。把那个 refactorer 的特种兵，连人带文件全部回滚到 'original' 的快照状态。"*

一记 `agent_restore` 砸下去，整个 VFS 在字节层面上瞬间被拨回了打标签时的那个瞬间。旁边跑着的其他特种兵连一根汗毛都没被惊动。

### 扒开两个快照看看这中间到底发生了什么

> *"把 'original' 快照和现在它搞出的烂摊子之间的差异 (diff) 全给我扒出来。"*

`agent_diff` 给出的验尸报告分极其残暴的三截：哪些文件冒出来了、蒸发了、或是被篡改了 (靠内容哈希对齐)；哪些 KV 状态的破键值挪了窝，前脚长啥样，后脚长啥样；以及在这两张快照之间，这只畜生到底抄起兵器乱砍了多少下 (调用链)。

把它当成一种为了查 bug 而存在的时光机器就行了 —— 把这只特种兵每走一步的脚印全放在显微镜下，看完后一把火烧干净，绝不会殃及隔壁任何无辜的兄弟。

> **顺藤摸瓜。** [教程/t02 — 端到端自愈实战](t02-e2e-self-healing.md) —— 从一眼看穿那个修歪了的破补丁，到极其暴力的外科手术级回滚，再到去流水账里揪出罪魁祸首，全部一套连招带走。极其残暴的 0.3 秒沙盒级单兵回滚。

## Step 8 — 升堂拷问：拿 SQL 给尸检定谳 (3 分钟)

一旦有特种兵翻车了，所有的罪证早就在数据库里躺好了。这 4 个极其毒辣的提示词 (prompt) 几乎能罩住所有的灾后复盘：

> *"把所有特种兵里，那些报错了的兵器挥动记录 (tool calls) 全给我揪出来。"*

```sql
SELECT a.name, tc.tool_name, tc.error, tc.timestamp
FROM tool_calls tc JOIN agents a ON tc.agent_id = a.agent_id
WHERE tc.status = 'error'
ORDER BY tc.timestamp DESC;
```

> *"把那个翻车阵亡的特种兵，生平所有的流水账按时间线给我列出来。"*

```sql
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = '...' ORDER BY event_id;
```

> *"到底哪个畜生吃的 token 最多？"*

```sql
SELECT a.name, SUM(tc.token_count) AS tokens
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
GROUP BY a.agent_id ORDER BY tokens DESC LIMIT 5;
```

> *"那只发疯的特种兵到底弄脏了哪些文件？"*

```sql
SELECT path, version, modified_at FROM files
WHERE agent_id = '...' AND deleted = 0
ORDER BY modified_at;
```

这同样的拷问，你可以直接绕过大模型，在命令行里亲手敲：

```bash
uv run bene query "SELECT name, status FROM agents"
uv run bene query "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
```

而且，既然 `bene.db` 就是一个比白开水还普通的 SQLite 文件，你那些早就用顺手的极品老哥 —— DBeaver、DataGrip、甚至是极其复古的 `sqlite3` CLI —— 全都能直接把它怼开。

> **顺藤摸瓜。** [教程/t05 — 凌晨两点急救手册](t05-incident-response.md) 里展现了拿这些原模原样的 SQL 咒语去极其冷血地排障的极速流程 —— 从警报响起，到抓出真凶抛出修复方案，全程仅仅 12 秒。直接把那些 SQL 拷过去塞进你的排障手册 (runbook) 里。

## 你到底折腾出了一件什么神仙兵器

| 拿到的超能力 | 是靠什么黑魔法搞定的 |
|---|---|
| 多 Agent 指挥权 | Claude Code + BENE MCP 全套兵器 |
| 铁桶般的沙盒隔离 | 人手一个 VFS 结界，被 SQL 的物理约束死死按住 |
| 长着脑子的路由分发 | 梯队 (Tier) 给任务贴难度标签 → 派发给最门当户对的模型 |
| 并排狂飙的冲锋阵列 | 一口气能放 8 只 (想拉爆的话随便改) |
| 时光机级别的读档重来 | 任何一只 agent 都能被随时拍快照、随时踹回过去 |
| 无法篡改的底裤账本 | 只能硬塞不能篡改的事件台账，涵盖 14 种死法与活法 |
| 万物皆可 SQL 拷问 | 烧掉的代币、报错、文件修改、每一次抽搐，全能查 |
| 重复劳动的究极去重 | 靠 SHA-256 哈希寻址块，叠加 zstd 极限压缩 |
| 装在口袋里的运行库 | `cp bene.db backup.db` = 这就是全部家当的备份 |
| 永远账单为零 | 全在你的本地显卡上死命跑 |
| 底裤绝对不外露的数据隐私 | 没有任何一滴数据能爬出你这台机器的网卡 |

## 极简说明书 (Reference)

### `bene.yaml` — 扒光所有的配置项

```yaml
database:
  path: ./bene.db              # 数据库的藏身处
  wal_mode: true               # 强开 WAL 模式防卡死 (极其推荐开着)
  busy_timeout_ms: 5000        # SQLite 抢不到锁时的挣扎时间
  max_blob_size_mb: 100        # 数据库里死活不准超过这个大小的巨物
  compression: zstd            # 二进制大块的压榨机: zstd | none
  gc_interval_minutes: 30      # 扫地大妈过来清垃圾的频率

isolation:
  mode: logical                # 逻辑结界 (默认) | fuse 挂载 (Linux 专属黑科技)
  fuse_mount_base: /tmp/bene   # FUSE 挂载点的老巢 (Linux 专属)
  cgroups:
    enabled: false             # 靠 cgroup 暴力掐资源 (Linux 专属)
    memory_limit_mb: 4096
    cpu_shares: 1024

models:
  <给它起个响亮的名字>:
    provider: local | openai | anthropic       # 找谁拜码头 (默认是本地的 local)
    vllm_endpoint: http://localhost:8000/v1    # 本地主子的老接口 (留着擦屁股用的)
    endpoint: http://localhost:8000/v1         # 本地主子的新接口
    model_id: gpt-4o                           # 云端阔佬 (openai / anthropic) 专用的名号
    api_key_env: OPENAI_API_KEY                # 供着密钥的环境变量名字
    max_context: 32768                         # 脑容量极限 (tokens)
    use_for: [trivial, moderate, ...]          # 接客名单：什么难度的活归它管

router:
  type: tier                    # 阶级社会路由 (目前只有这个能选)
  classifier_model: <名字>       # 给任务贴难度条形码的打工人
  fallback_model: <名字>         # 大家都跑路的时候，出来擦屁股的兜底老哥
  context_compression: true     # 强开记忆摘要多段压缩机
  max_retries: 3                # 放弃治疗前的挣扎次数

ccr:
  max_iterations: 100           # 逼死 agent 前最多让它绕多少圈
  checkpoint_interval: 10       # 每熬过 N 圈就强制按头存个档
  timeout_seconds: 3600         # agent 的阳寿极限 (默认 1 小时)
  max_parallel_agents: 8        # 同时在外面撒野的狼群上限

mcp:
  port: 3100                    # SSE 通讯隧道的破门
  host: 127.0.0.1               # SSE 通讯隧道的门牌号

logging:
  level: INFO
  file: ./bene.log
```

### 能够操控生死的环境变量

| 变量名 | 默认值 | 到底是干嘛的 |
|---|---|---|
| `BENE_DB` | `./bene.db` | 数据库的藏身处 |
| `BENE_CONFIG` | `./bene.yaml` | 配置文件的藏身处 |
| `ANTHROPIC_API_KEY` | — | `provider: anthropic` 云端大户的敲门砖 |
| `OPENAI_API_KEY` | — | `provider: openai` 云端大户的敲门砖 |

### 给 Claude Code 开门的 `settings.json`

```json
{
  "mcpServers": {
    "bene": {
      "command": "uv",
      "args": [
        "run", "--project", "/path/to/bene",
        "bene", "serve", "--transport", "stdio",
        "--db", "/path/to/bene/bene.db",
        "--config-file", "/path/to/bene/bene.yaml"
      ]
    }
  }
}
```

## 排雷自救手册

| 被什么糊了一脸 (Symptom) | 八成是哪个倒霉催的弄的 (Likely cause) | 该怎么抢救 (Fix) |
|---|---|---|
| `Connection refused` 咬死了 `localhost:8000` | vLLM 压根就没爬起来 | 去跑 `vllm serve <model> --port 8000`；拿 `curl /v1/models` 戳一下看死没死 |
| Claude Code 眼瞎看不见 BENE 兵器谱 | `settings.json` 被你写了个错别字，或者路径瞎指 | 滚去查 JSON 格式；把 Claude Code 掐死重开；去干拉一下服务端 (看 Step 4 里的排雷指南) |
| Agent 像智障一样死循环或者装死 | 工具调用链卡死了，或者它在疯狂鬼畜 | `uv run bene ls` 查一下 → `uv run bene kill <id>` 强制超度；把 `max_iterations` 往下压一压 |
| 显卡被活生生撑爆 (OOM) | 模型太肥，或者你放出的狼太多了 | 换个瘦点的模型；在 vLLM 那加个 `--gpu-memory-utilization 0.8`；把 `max_parallel_agents` 给掐小点；或者去搞个被压榨过的模型 (GPTQ, AWQ) 凑合一下 |
| `Model not found` 找不到模型 | 你在 `bene.yaml` 里写的名字，跟 vLLM 那边报上来的名字对不上暗号 | 去跑一把 `curl /v1/models \| jq`，一字不差地把里面的名号抄过来 |
| 数据库被死死锁住 (Database locked) | 一群人在那抢写入权，但你却没开 WAL 模式 | 赶紧把 `wal_mode: true` 焊上去；千万别特么把 `bene.db` 放在网络共享盘上作死 |
| 上下文太长 (Context too long) | 提示词长得跟裹脚布一样，装不下了 | 在 router 里把 `context_compression: true` 给我开起来；把废话砍短；或者把 `max_context` 拉高，跟 vLLM 那边的数字对齐 |

## 接下来的坑在哪里

挑你最缺的东西看：

- [教程/t00 — 端到端通关大纲](t00-bene-e2e-walkthrough.md) — *在 5 分钟内极其丝滑地走完 `空降 → 快照 → 拷问 → 时光倒流` 的流程，* 而且根本不带 LLM 玩。这是你这辈子最快摸清那本流水账怎么读的捷径。
- [教程/t02 — 端到端自愈实战](t02-e2e-self-healing.md) — *沙盒里的时光倒流。* 一场残暴的 0.3 秒沙盒级单兵回滚实盘教学。
- [教程/t03 — 安全攻防特种部队](t03-security-swarm.md) — *极其冷血的人格分裂实证。* 零跨界偷看、严苛的锚定偏差 (anchoring-bias) 量化测量、还有霸气的 SQL 聚合统计。
- [教程/t05 — 凌晨两点急救手册](t05-incident-response.md) — *那些拿着纯 SQL 拷问审计库的神级咒语*，直接 Ctrl+C / Ctrl+V 到你的排障手册 (runbook) 里。
- [教程/t06 — ML 炼丹实验室](t06-ml-research-lab.md) — *派出 N 匹脑洞大开的 agent 熬夜炼丹。* 这里才是那套本地阶级化模型路由编队真正值回票价的地方。
- [教程/t10 — 具备自愈能力的 CI 守夜人](t10-ci-overnight-bene-swarm.md) — *高阶绝活；把这套玩意焊死在生产级 CI 里。* 教你怎么把同样的这堆零件，极其残暴地镶嵌在 GitHub Actions 上。
- [深层架构](../architecture.md), [数据库解剖图](../schema.md), [CLI 指令大黄页](../cli-reference.md) — 这三本是用来垫桌脚的底层说明书。
- 拿去就能跑的硬核实战脚本: [`examples/code_review_swarm.py`](../../examples/code_review_swarm.py), [`examples/parallel_refactor.py`](../../examples/parallel_refactor.py), [`examples/self_healing_agent.py`](../../examples/self_healing_agent.py), [`examples/post_mortem.py`](../../examples/post_mortem.py)。

---

*BENE 基于 MIT 协议开源，并且是一个极端的纯本地原教旨主义者。没有任何一滴数据能溜出你的网线。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
