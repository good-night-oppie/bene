# 部署 BENE (Deployment)

这篇指南将手把手带你从一台光秃秃的裸机，一路杀进生产环境：装好 BENE、拉起模型服务端、把它们俩都做成能自动诈尸重启的后台服务、以及在炸机时该去哪里翻垃圾桶。

> **BENE 脑子里的所有东西全被死死锁在一个 SQLite 文件里 —— `cp` 一下就等于做了全量备份；除非你故意把它指向外网，否则没有任何一滴数据会流出你的机器。**

原版导航传送门: [前置要求 (Prerequisites)](#prerequisites), [源码安装 (Installation from Source)](#installation-from-source), [搞定 vLLM (vLLM Setup)](#vllm-setup), [扒光配置文件 (Configuration Walkthrough)](#configuration-walkthrough), [做成系统服务 (Running as a Service)](#running-as-a-service-systemd), [Docker 部署 (Docker Deployment)](#docker-deployment), [性能榨汁机 (Performance Tuning)](#performance-tuning), [排雷自救手册 (Troubleshooting)](#troubleshooting).

---

<a id="installation-from-source"></a>

## 三步装完，废话少说

```bash
git clone https://github.com/good-night-oppie/bene.git
cd bene
uv sync
```

`uv sync` 会就地捏出一个 `.venv` 虚拟环境，把所有的包全塞进去。

<a id="prerequisites"></a>

### 你这破机器得满足什么条件

| 硬性要求 | 及格线 | 推荐配置 |
|---|---|---|
| Python | 3.11 | 3.12+ |
| uv | 0.4+ | 最新版 |
| SQLite | 3.35+ (必须带 WAL 模式) | 系统自带的就行 |
| 操作系统 | Linux, macOS, Windows | Linux (只有它才能玩 Tier 2 结界) |

如果你打算在本地跑 LLM 推理，还得加上：

| 额外要求 | 拿来干嘛的 |
|---|---|
| NVIDIA 显卡 | 在本地跑 vLLM 暴力推理 |
| CUDA 12.1+ | vLLM 的底层引擎 |
| vLLM 0.4+ | 模型服务端 |
| fusepy | Tier 2 级别的 FUSE 沙盒隔离 (Linux 专属) |
| uvicorn + starlette | 给 MCP 服务端跑 SSE 通讯隧道的 |

没装 `uv`？一句话搞定：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 验货
uv --version
```

### 选装包 (Optional extras)

带上 `dev` 后缀，就能把 pytest、pytest-asyncio、pytest-cov 和 ruff 这帮开发用的老哥请进来：

```bash
uv sync --extra dev
```

如果你想玩 Tier 2 级别的 FUSE 沙盒隔离 (仅限 Linux)，那就得把 `fusepy` 扯进来：

```bash
uv sync --extra fuse
```

### 验验成色

查三样：CLI 活没活、测试能不能跑、以及一次纯内存里的生死轮回：

```bash
# 看看 CLI 死没死
uv run bene --version

# 把测试套件抽一遍
uv run pytest

# 极速点火试车 (Smoke test)
uv run python -c "
from bene import Bene
afs = Bene(':memory:')
agent = afs.spawn('smoke-test')
afs.write(agent, '/hello.txt', b'Hello from BENE!')
print(afs.read(agent, '/hello.txt'))
afs.close()
print('OK')
"
```

### 甩掉 `uv run` 这个拐杖

如果你想在终端里直接裸敲 `bene`，而不是每次都拖着个 `uv run`：

```bash
uv tool install -e .
```

---

<a id="vllm-setup"></a>

## 把模型端上来

只要它长着一张兼容 OpenAI 的脸，BENE 就能把它当牛使。我们官方推荐的标配是本地 vLLM —— 每个难度梯队独享一个服务端进程 —— 不过你先拿单张显卡跑跑也凑合。

### 单卡单模型的穷人玩法

就一张显卡，就一个模型？那就把所有的难度分级全砸在它头上：

```yaml
models:
  my-model:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]
```

### 阶级森严：三梯队全量编队

梯队路由器 (tier router) 的杀手锏，就在于能把便宜的破事全扔给不要钱的破模型：

| 梯队 | 样板模型 | 脑容量 | vLLM 端口 | 拿来干嘛的 |
|---|---|---|---|---|
| 矮子 (7B) | Qwen/Qwen2.5-Coder-7B-Instruct | 32K | 8000 | 无脑脏活、给任务贴标签、当分诊员 |
| 中产 (32B) | Qwen/Qwen2.5-Coder-32B-Instruct | 128K | 8001 | 敲日常代码、写测试用例 |
| 大佛 (70B) | deepseek-ai/DeepSeek-R1-70B | 128K | 8002 | 骨灰级推理、系统架构、画大饼 |

7B — 专门负责分诊和打杂的底层苦力：

```bash
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
  --port 8000 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --tensor-parallel-size 1
```

32B — 干活的主力牛马：

```bash
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct \
  --port 8001 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
```

70B — 供起来专门啃骨头的：

```bash
vllm serve deepseek-ai/DeepSeek-R1-70B \
  --port 8002 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 4
```

### 这帮祖宗要吃多少显存 (VRAM)

| 模型体型 | 砸锅卖铁底线 | 推荐配置 | 张量并行 (Tensor Parallel) |
|---|---|---|---|
| 7B | 16 GB (1张卡) | 24 GB | 1 |
| 32B | 48 GB (2张卡) | 80 GB | 2 |
| 70B | 160 GB (4张卡) | 320 GB | 4-8 |

### 拿棍子戳戳看死活

```bash
# 把每个口子都戳一遍
curl http://localhost:8000/v1/models
curl http://localhost:8001/v1/models
curl http://localhost:8002/v1/models
```

没死的话，它会吐一坨 JSON 出来，大声报出自己的名号。

### 本地没卡？花钱去外面找只鸡

接外面的远程接口跟本地玩是一模一样的 —— 换个网址就行了：

```yaml
models:
  remote-model:
    vllm_endpoint: https://my-gpu-server.example.com/v1
    max_context: 131072
    use_for: [complex, critical]
```

---

<a id="configuration-walkthrough"></a>

## 扒光 bene.yaml 的底裤

先把随代码附赠的那个样板抄一份，然后对着它开刀：

```bash
cp bene.yaml.example bene.yaml
```

### 全文无死角解剖

```yaml
# ── 数据库 (Database) ────────────────────────────────────────
database:
  path: ./bene.db              # SQLite 那个破文件的落脚点
  wal_mode: true                # 强开 WAL 模式防卡死 (极其推荐开着)
  busy_timeout_ms: 5000         # 抢不到写锁时，挣扎多久才放弃 (毫秒)
  max_blob_size_mb: 100         # 死活不准超过这个体型的单体巨物
  compression: zstd             # 榨汁机选项: "zstd" 还是 "none"
  gc_interval_minutes: 30       # 扫地大妈多久出来清理一次没主的孤儿碎片

# ── 隔离结界 (Isolation) ───────────────────────────────────────
isolation:
  mode: logical                 # "logical" (默认), "fuse", 或者 "namespace"
  fuse_mount_base: /tmp/bene # FUSE 结界的老巢 (Linux 专属黑科技)
  cgroups:
    enabled: false              # 强行戴上 cgroups v2 的镣铐
    memory_limit_mb: 4096       # 饿死 agent 前最多给多少内存
    cpu_shares: 1024            # 抢 CPU 时的权重

# ── 模型巢穴 (Model Endpoints) ──────────────────────────────────────────
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768          # 脑容量极限 (tokens)
    use_for:                    # 认领的脏活累活
      - trivial
      - code_completion

  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for:
      - moderate
      - code_generation

  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for:
      - complex
      - critical
      - planning

# ── 梯队路由 (Tier Router) ────────────────────────────────────
router:
  type: tier                    # 阶级社会路由 (目前只有这个)
  classifier_model: qwen2.5-coder-7b   # 抓个模型来当分诊员
  fallback_model: deepseek-r1-70b      # 大家都跑路的时候，用来擦屁股的大哥
  context_compression: true     # 强开脑容量压缩机
  max_retries: 3                # 放弃治疗前的挣扎次数

# ── 跑圈引擎 (CCR) ────────────────────────────
ccr:
  max_iterations: 100           # 逼死 agent 前最多让它绕多少圈 (plan-act-observe)
  checkpoint_interval: 10       # 每熬过 N 圈就强制按头存个档
  timeout_seconds: 3600         # Agent 的阳寿极限 (1 小时)
  max_parallel_agents: 8        # 并排狂飙的冲锋阵列人数上限

# ── MCP 服务端 ─────────────────────────────────────
mcp:
  port: 3100                    # SSE 隧道的破门
  host: 127.0.0.1              # 绑死的门牌号

# ── 碎碎念 (Logging) ──────────────────────────────────────────────────
logging:
  level: INFO                   # 碎碎念的下限: DEBUG, INFO, WARNING, ERROR
  file: ./bene.log             # 日志文件扔哪
```

### 决定生死的那四个旋钮

**`database.compression`** — `zstd` (默认项) 会拿着三档压缩死命榨干每一块碎片：体积能缩极多，CPU 也不怎么喊疼。只有当你那台破服务器 CPU 已经被榨干、并且你还在疯狂往里塞垃圾时，才去切成 `none`。

**`isolation.mode`** — 三重结界，一层比一层丧心病狂：

- `logical` (默认) 纯靠 SQL 语法硬防 —— 一分钱不用花，随便什么系统都能跑。
- `fuse` 强行挂载一个单兵专属 VFS；这玩意只认 Linux 和 fusepy。只要你的 agent 会跑点奇奇怪怪的系统命令、并且指望硬盘上真有这个文件，你就得捏着鼻子选它。
- `namespace` 直接动用 Linux 命名空间外加 cgroups 戴镣铐；必须有 Linux 和 root 权限。专门用来关押那些你极度不信任的脏活。

**`router.classifier_model`** — 把这活丢给你池子里最小、最快的那个模型。它的提示词极短，而且被死死掐在了 `max_tokens=10`，所以哪怕是个 7B 也能秒回且算得很准。如果你连这个都不写，BENE 就会退化成纯正则匹配的老古董 (纯看长相，一行 LLM 都不跑)。

**`router.context_compression`** — 把它打开，BENE 就会在每次发包前极其残暴地修剪上下文：把之前工具吐出来的长篇大论全截断、并且抛弃最早的闲聊记录，保证你永远不会撞到爆显存的南墙。它会死死卡住模型 `max_context` 的 85% 来下刀，留出余量让模型能把话说完。

---

<a id="running-as-a-service-systemd"></a>

## 塞进 systemd 当成牛马使唤

### BENE MCP 隧道服务

把这坨东西糊到 `/etc/systemd/system/bene-mcp.service` 去：

```ini
[Unit]
Description=BENE MCP Server
After=network.target

[Service]
Type=simple
User=bene
Group=bene
WorkingDirectory=/opt/bene
ExecStart=/opt/bene/.venv/bin/bene serve --transport sse --host 127.0.0.1 --port 3100 --db /var/lib/bene/bene.db --config-file /etc/bene/bene.yaml
Restart=on-failure
RestartSec=5
Environment=BENE_DB=/var/lib/bene/bene.db
Environment=BENE_CONFIG=/etc/bene/bene.yaml

# 铁桶防御 (Security hardening)
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/bene
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

底下那一堆防黑客选项能确保它就算抽风了也造不了反：绝不允许提权、系统盘只读、想撒野只能在 `/var/lib/bene` 那个笼子里撒。

### 每个梯队的模型各占一个坑

这是 7B 的笼子，塞进 `/etc/systemd/system/vllm-7b.service`：

```ini
[Unit]
Description=vLLM 7B Model Server
After=network.target

[Service]
Type=simple
User=vllm
Group=vllm
ExecStart=/opt/vllm/.venv/bin/vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000 --max-model-len 32768 --gpu-memory-utilization 0.85
Restart=on-failure
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0

[Install]
WantedBy=multi-user.target
```

剩下的两尊大佛如法炮制：32B 霸占 8001 端口并且绑死 `CUDA_VISIBLE_DEVICES=1,2`，70B 盘踞在 8002 端口并且骑着 `CUDA_VISIBLE_DEVICES=3,4,5,6`。

### 全军出击

```bash
# 捏个没法登系统的僵尸账号，顺便把狗窝建好
sudo useradd -r -s /bin/false bene
sudo mkdir -p /var/lib/bene /etc/bene
sudo chown bene:bene /var/lib/bene

# 把配置抄过去
sudo cp bene.yaml /etc/bene/bene.yaml

# 开机自启
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-7b vllm-32b vllm-70b
sudo systemctl enable --now bene-mcp

# 验尸
sudo systemctl status bene-mcp
sudo journalctl -u bene-mcp -f
```

---

<a id="docker-deployment"></a>

## 躲在 Docker 壳子里跑

下面这张镜像会把通过 SSE 协议暴露 MCP，并且把那个破数据库甩到外挂卷里。

### 捏镜像

```dockerfile
FROM python:3.12-slim

# 把 uv 生拽过来
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 把家当搬进去
COPY pyproject.toml uv.lock ./
COPY bene/ bene/

# 把包全打进去
RUN uv sync --frozen --no-dev

# 给数据库留个坑
RUN mkdir -p /data

# 默认开打：SSE 模式的 MCP 隧道
CMD ["uv", "run", "bene", "serve", "--transport", "sse", "--host", "0.0.0.0", "--port", "3100", "--db", "/data/bene.db", "--config-file", "/app/bene.yaml"]

EXPOSE 3100

VOLUME ["/data"]
```

### Compose 大礼包：BENE 挂着一只 7B 模型

```yaml
services:
  bene:
    build: .
    ports:
      - "3100:3100"
    volumes:
      - bene-data:/data
      - ./bene.yaml:/app/bene.yaml:ro
    depends_on:
      - vllm-7b
    restart: unless-stopped

  vllm-7b:
    image: vllm/vllm-openai:latest
    command: >
      --model Qwen/Qwen2.5-Coder-7B-Instruct
      --port 8000
      --max-model-len 32768
      --gpu-memory-utilization 0.85
    ports:
      - "8000:8000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  bene-data:
```

### 踢一脚看看

```bash
docker compose up -d

# 蹲点看日记
docker compose logs -f bene

# 隔着壳子执行命令
docker compose exec bene uv run bene ls --db /data/bene.db
```

### 被网络坑死的雷区

在 Compose 的世界里，`localhost` 会直接撞到自己脸上。你得在 `bene.yaml` 里老老实实拿服务名去点名：

```yaml
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://vllm-7b:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]
```

---

## 拿什么证明系统没死

既然它把整条命都拴在一个 SQLite 身上，那所谓的健康检查无非就是敲几行 SQL 的事 —— 连狗屁仪表盘都不需要：

```bash
# 查骨架版本
bene query "SELECT * FROM schema_version"

# 看看这头猪到底吃了多少斤的料
bene query "
SELECT 'agents' as tbl, COUNT(*) as rows FROM agents
UNION ALL SELECT 'files', COUNT(*) FROM files
UNION ALL SELECT 'blobs', COUNT(*) FROM blobs
UNION ALL SELECT 'tool_calls', COUNT(*) FROM tool_calls
UNION ALL SELECT 'state', COUNT(*) FROM state
UNION ALL SELECT 'events', COUNT(*) FROM events
UNION ALL SELECT 'checkpoints', COUNT(*) FROM checkpoints
"

# 查 WAL 到底开没开
bene query "PRAGMA journal_mode"

# 全身体检
bene query "PRAGMA integrity_check"
```

这套查询接口 (query) 是被焊死在只读模式的，所以就算你闭着眼睛敲健康检查，也绝对搞不坏任何东西。

---

<a id="performance-tuning"></a>

## 性能榨汁机

### 给 SQLite 喂猛药

`Bene.__init__()` 每次握手时都会强塞这几口药：

```python
conn.execute("PRAGMA journal_mode=WAL")     # 众人拾柴齐发力 (Concurrent reads)
conn.execute("PRAGMA foreign_keys=ON")       # 别特么乱指空坟 (Referential integrity)
conn.execute("PRAGMA busy_timeout=30000")    # 抢不到锁先忍 30 秒
conn.execute("PRAGMA wal_autocheckpoint=100") # 满 100 滴血就清一次账
```

还在嫌并发不够变态？那就在继承 `Bene` 或者搞连接池时，再给它糊上这几剂禁药：

```sql
PRAGMA synchronous=NORMAL;       -- 拿命换速度 (断电可能会丢最后一秒的档)
PRAGMA cache_size=-64000;        -- 赏它 64MB 的页缓存 (平时抠门到只给 2MB)
PRAGMA mmap_size=268435456;      -- 256MB 的内存映射暴搜
PRAGMA temp_store=MEMORY;        -- 临时烂账全在内存里糊
```

### 那个 `.db` 文件放哪极其致命

- 老老实实把它放在 **本地固态硬盘 (SSD)** 上。WAL 模式只要一闻到网络文件系统的味道就会当场暴毙 —— 别特么想着 NFS 或者 SMB。
- 放在 tmpfs/ramfs (纯内存盘) 里跑得飞起，代价是你重启之后就只剩一条内裤了。
- 拿 Docker 跑的时候，必须挂上命名卷 (named volume) 或者直接绑在本地 SSD 上的目录里。

### 榨汁机选项：要命还是要空间

| 怎么选 | 写的有多疼 | 读的有多疼 | 到底能压多扁 | 什么时候上 |
|---|---|---|---|---|
| `zstd` | 稍微有点卡 | 稍微有点卡 | 原体积的 40-70% | 万金油默认项 |
| `none` | 快到飞起 | 快到飞起 | 原封不动的大肉块 | 你的破 CPU 已经被榨干了，而且文件都是指甲盖大小的 |

### 手动油门上的三个转速表

- `ccr.max_parallel_agents` 捏着异步信号量的咽喉。这玩意必须看你显存和 vLLM 的脸色行事 —— 每一匹在跑的狼，都会把它的整套黑历史硬塞在你显存里。
- `database.busy_timeout_ms` 当你开始狂飙并发、而且屏幕上频频闪过 `database is locked` 时，把它往上狂拉；拉到 10000 甚至 30000 都不丢人。
- vLLM 里的 `--max-num-seqs` 卡着模型那边能同时接多少客。让它跟 `max_parallel_agents` 并驾齐驱，免得两头互相干等着浪费青春。

### 收尸大队清理乱葬岗

被覆盖掉的旧文件和被直接删掉的尸体，会留下满地的孤儿碎片 (orphaned blobs)。时不时去给它们扫个墓：

```python
from bene import Bene

afs = Bene("bene.db")
removed = afs.blobs.gc()
print(f"Removed {removed} orphaned blobs")
afs.close()
```

看看底下还烂了多少无主之物等着你去扫：

```bash
bene query "SELECT COUNT(*) as orphaned FROM blobs WHERE ref_count <= 0"
```

虽然 `gc_interval_minutes` 已经写在配置文件里了，但全自动垃圾回收的定时器目前还没装上 —— 所以在那之前，这种扫地的工作只能你自己亲自动手了。

---

<a id="troubleshooting"></a>

## 排雷自救手册

### vLLM 抵死不从 (Connection refused)

BENE 在你指的那个口子上扑了个空。

1. 亲自拿棍子去捅那个口子：`curl http://localhost:8000/v1/models`
2. 去翻 `bene.yaml`，看看那个端口是不是写串行了。
3. 如果是在 Docker 壳子里，别傻敲 `localhost`，拿它的名字去敲门 —— `http://vllm-7b:8000/v1`。
4. 滚去看 vLLM 的日记，看看是不是显存爆了或者模型压根就没加载起来。

### 门锁死了进不去 ("database is locked")

一群大老粗抢写锁，而且死皮赖脸抢的时间超过了超时极限。

1. 去 `bene.yaml` 里把 `busy_timeout_ms` 往死里拉 —— 15000 或者 30000 都行。
2. 拿命去查 WAL 到底开没开 —— `bene query "PRAGMA journal_mode"` 必须老老实实回你一个 `wal`。
3. 保证那个 `.db` 是长在本地硬盘上的，绝对不是从 NFS/SMB 里伸出来的触手。
4. 把 `max_parallel_agents` 往下按一按，别让那么多人一起去抢门把手。

### 脑容量溢出了 (Out of context window)

这段漫长而又废话连篇的对话，把模型的脑子给撑爆了。

1. 强开截肢手术：`router.context_compression: true`
2. 把 `ccr.max_iterations` 掐死点，别让这破对话聊到天荒地老。
3. 把 `ccr.checkpoint_interval` 往上拉 —— 自动存盘的次数少了，废话就少了。
4. 如果真是个宏篇巨著的任务，把它扔给脑容量更大的老大哥模型去办。

### 内存吃爆了

场上还活着的特种兵太多了，或者那个垃圾场里的碎片已经堆成了山。

1. 把 `ccr.max_parallel_agents` 往下砍。
2. 喊收尸大队出来干活：`afs.blobs.gc()`
3. 那些已经结案的老东西，全都给我导出到废纸篓数据库里去：`bene export <agent_id> -o archive.db`
4. 心里得有点数，你拨给 `PRAGMA cache_size` 的那个天价内存，就是生生从系统里抠出来的。

### FUSE 结界立不起来

想玩 Tier 2 隔离？它只认 Linux，而且必须带上 fusepy 那个包。

1. 验明正身：`uname -s`
2. 把缺失的组件给我补上：`uv sync --extra fuse`
3. 看看内核模块长齐了没：`lsmod | grep fuse`
4. 如果是权限被打回来了，去 `/etc/fuse.conf` 里加上 `user_allow_other`。
5. 只要你不是在正经的 Linux 里跑，老老实实退回去用 `isolation.mode: logical`。

### "查无此人: <id>"

你在名册上点了个压根就不存在的名字。

1. 睁眼看看名册上都有谁：`bene ls`
2. Agent ID 是那种极其反人类的 26 位 ULID 乱码 —— 你打错一个字都很正常。
3. 拍拍脑子想想，这哥们是不是已经被你导出扔掉了，或者你现在是不是跑错片场（连错 `.db`）了？

### "只能用只读命令来拷问 (Only read-only queries are allowed via query())"

这特么是故意的：`query()` 和那个叫 `agent_query` 的 MCP 兵器只能接只读的 SQL。想往里面写东西？滚去走 Python API；这个拷问接口的存在，纯粹是为了让你查房、盯盘、和验尸的。
