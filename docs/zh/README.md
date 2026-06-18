# BENE 文档

在本地机器上运行一组 AI agent 蜂群，监测它们的一举一动，并能随时回滚任何被它们搞砸的操作。

> **每个 agent 的文件、每一次事件、每一个 checkpoint —— 全部记录在一个你可以直接 `cp` 复制的 SQLite 文件里。没有潜藏的云端依赖。**

BENE (Breeding-program Evolutionary Nexus for Engrams) 为每个 agent 分配专属的私有文件系统，提供自动 checkpoint 机制、实时看板，以及一份完全支持 SQL 查询的审计追踪（audit trail）。

---

## 极速起步：从 clone 到 demo

```bash
git clone https://github.com/good-night-oppie/bene.git && cd bene
uv sync
uv run bene setup       # 配置模型，初始化数据库，安装 MCP server
uv run bene demo        # 观看运行效果 —— 完全不需要 API key
```

---

## 从编辑器中直接驱动

运行 `uv run bene setup` 后，Claude Code、Cursor 以及其他任何 MCP client 都可以用自然语言直接驱动 BENE：

```text
with bene, 帮我 review payments 模块 —— 让安全 agent 和测试 agent 并行工作
```

```text
with bene, 重构 auth.py —— 并行执行实现、测试和文档更新
```

```text
with bene, 找出上次运行中所有失败的 agent，并展示它们遭遇了什么错误
```

客户端配置以及全部 37 个 MCP tools 的清单，请见：[MCP 整合方案](mcp-integration.md)。

---

## 核心机制

**虚拟文件系统 (VFS)** —— 每个 agent 都在数据库内的私有文件系统中工作。没有任何 agent 能越权读取其他 agent 的文件：隔离性是由底层的 SQL 约束（`WHERE agent_id = ?`）来保证的，而不是靠代码约定。

**Checkpoint (快照)** —— 将单个 agent 的文件和 KV 状态冻结在特定时刻。毫秒级恢复；对两个 checkpoint 进行 diff 即可精准掌控变动。详见 [Checkpoints](checkpoints.md)。

**审计追踪 (Audit trail)** —— 文件读写、tool 调用、状态变更、生命周期事件：每一次动作都作为一条不可篡改的（append-only）记录写入 `events` 表，随时可以用 SQL 查询。表结构设计：[Schema 数据库大纲](schema.md)。

**Tier 路由器** —— 难度感知路由（Difficulty-Aware Routing by Tier）负责将任务分配给合适的模型层级：琐碎的工作交给本地 7B 模型，复杂的硬核任务则路由给 70B 模型或 Claude。内部原理：[架构解析](architecture.md)。

**单 `.db` 文件存储** —— 没有独立的服务进程，不需要配置云账号。仅靠一个 SQLite 文件，你就可以通过 `cp` 进行备份，用任意 SQLite 工具打开检视，或者直接发给你的队友。

---

## 场景导航

| 你的需求... | 指南 | 内容概要 |
|---|---|---|
| 实时观测 | [Dashboard 看板](dashboard.md) | Agent 活动的甘特图，单 agent 探查器，实时事件流，多项目视图 |
| 编写脚本 | [CLI 参考手册](cli-reference.md) | 每一个命令、每一个 flag 的详尽说明 |
| 撤销错误 | [Checkpoints 机制](checkpoints.md) | 状态快照与回滚，对比两次 checkpoint，自动 checkpoint 策略及存储原理 |
| 共享记忆 | [跨 Agent Memory](memory.md) | 在不同 agent 和不同 session 间共享支持 FTS5 检索的记忆 |
| 复用技能 | [Skill 技能库](skills.md) | 共享支持 FTS5 检索的程序化技能模板，并跟踪使用情况 |
| 协同决策 | [Shared Log 共享日志](shared-log.md) | LogAct 协议：声明意图 (intent) → 投票 (vote) → 决断 (decide) |
| 调优 harness | [Meta-Harness 演化搜寻](meta-harness.md) | 对 prompt 和执行策略的自动化参数搜寻 |
| 借鉴模式 | [应用场景 (Use Cases)](use-cases.md) | Code-review 蜂群，并行重构，自愈合 agent，事后复盘，事故响应，ML 研究 |

---

## 验证：教程与案例分析

**组件深度解析**：

| 教程 | 核心焦点 |
|---|---|
| [t11 — 基于 vLLM 的本地 Agent](tutorials/t11-local-agents-vllm.md) | 零成本、可审计的本地多 agent 栈 —— vLLM + Tier 路由 + Claude Code MCP |

**完整工作流演练** (端到端的实战场景)：

| 教程 | 实战场景 |
|---|---|
| [t00 — 端到端完整演练](tutorials/t00-bene-e2e-walkthrough.md) | **从此开始**。生成 → 运行 → checkpoint → 审计 → 恢复 → 导出 |
| [t01 — Meta-Harness: 胜率从 48% 提升至 83%](tutorials/t01-bene-meta-harness.md) | 15 轮自动化 prompt 及策略搜寻，总花费 $0.14 |
| [t02 — 端到端的自我愈合](tutorials/t02-e2e-self-healing.md) | 错误修复检测，外科手术式回滚，基于审计日志的根因分析 |
| [t03 — 安全审计蜂群](tutorials/t03-security-swarm.md) | 4 个审计 agent 并行工作，使用 SQL 聚合发现的安全隐患 |
| [t04 — 数据库迁移回滚](tutorials/t04-migration-rollback.md) | 200万行数据回填异常应对，0.3秒极速回滚 |
| [t05 — 生产事故响应](tutorials/t05-incident-response.md) | 基于 SQL 事件日志的 12 秒根因定位 |
| [t06 — ML 研究实验室](tutorials/t06-ml-research-lab.md) | 4 个负责验证假设的 agent 彻夜运行，通过 SQL 对比最终结果 |
| [t07 — 衰退防御 (Regression Guard)](tutorials/t07-regression-guard.md) | 拦截失败的模型替换，Meta-Harness 自动回滚到基线状态 |
| [t08 — 100 Agent 规模化运行](tutorials/t08-hundred-agents-scale.md) | 847 个 agent 规模化部署，hub 协调机制，节省 245 万 token |
| [t10 — CI 环境中的彻夜自愈](tutorials/t10-ci-overnight-bene-swarm.md) | GitHub Actions 中的衰退拦截、自动修复、以及代码 review 与重构蜂群 |

**真实案例研究** (Oppie 实际战役复盘)：

| 案例 | 成果 |
|---|---|
| [cs02 — 持续集成 (CI) 自愈](case-studies/cs02-ci-self-healing-refactor-swarm.md) | 多 agent CI 架构设计、核心洞察、软件供应链实践及跨团队影响力 |

---

## 示例脚本

位于仓库根目录的 `examples/` 下：

- `library_basics.py` — 演示基础 VFS 操作，不接入 LLM
- `code_review_swarm.py` — 4 个 review agent 并行工作
- `parallel_refactor.py` — 并行执行代码实现、测试和文档更新
- `self_healing_agent.py` — 自动在失败运行时触发 checkpoint 恢复
- `autonomous_research_lab.py` — 启动 N 个假设验证 agent，最后通过 SQL 对比输出结果
- `meta_harness_*.py` — 自动化的 prompt 和执行策略寻优

---

## 查阅资料

| 参考手册 | 内容概要 |
|---|---|
| [Schema 数据库大纲](schema.md) | 全景拆解 11 张 SQLite 表 —— 包含每一个字段和索引 |
| [架构解析 (Architecture)](architecture.md) | 系统划分、数据流转机制，以及设计背后的权衡与推演 |
| [部署指南 (Deployment)](deployment.md) | vLLM 配置、生产环境设置、Docker 容器化 |

---

## 融入你自己的 Agent

| 指南 | 内容概要 |
|---|---|
| [集成 BENE](integrating-bene.md) | 一份坦诚的地图：什么是开箱即用的，什么需要你自己手写连线 |
| [Probe (探针) 开发](probe-authoring.md) | 编写真正能失效拦截的 kill gate，然后通过 `bene probe run --json` 接入 CI |
| [原子化补全方案 (Atomic Completion)](recipes/atomic-completion.md) | 基于纯 SQLite/JSONL 日志实现的 Exactly-once（精确一次）、无幽灵执行的补全机制 —— 无需引入 Temporal |

---

## 设计哲学

[设计哲学 (Design Philosophy)](philosophy.md) 解释了 BENE 为什么选择采纳已发表的研究成果而不是重复造轮子，一项技术需要达到什么标准才会被采纳整合，以及系统的下一步演进方向。
