# 示例画廊

随 BENE 一起发布的、真实可跑的示例脚本，按各自演练的支柱分门别类。每一个都躺在仓库的 [`examples/`](../examples/) 目录下。

**分两类。** *独立运行*（standalone）的示例针对一个全新的 `bene.db` 开跑，不依赖任何外部服务 —— 在一次干净的 `pip install bene` 之后，已验证能以 0 退出码收尾。*依赖模型*（model-backed）的示例要驱动一整套 agent 循环，得有一个配好的 model provider 兜底（一个本地 vLLM 端点，或者 `bene.yaml` 里的一把 API key）；这类下文都打了标记。

随便挑一个，这样跑：

```bash
uv run python examples/<name>.py     # 从源码仓库里跑
```

> `examples/` 里的脚本只随源码仓库发布，**并不**塞进 PyPI 包里 —— 想跑就把仓库 clone 下来（或者单独拷一份脚本过去）。

## 每 agent 一套 VFS 与状态 (Per-agent VFS & state)

| 示例 | 演练了什么 | 怎么跑 |
|---|---|---|
| [`library_basics.py`](../examples/library_basics.py) | `Bene` API 端到端走一遍：建 agent、读写每 agent 私有的 VFS、设状态、列清单。 | 独立运行 ✓ |
| [`export_share.py`](../examples/export_share.py) | 把单个 agent 导出成一个独立的 `.db`，再到别处导入 —— 单文件 Nexus 化身一件可随身携带的产物。 | 独立运行 |

## 检查点与恢复 (Checkpoints & recovery)

| 示例 | 演练了什么 | 怎么跑 |
|---|---|---|
| [`post_mortem.py`](../examples/post_mortem.py) | 事后复盘式调试：打 checkpoint、翻事件日志、再做 diff，揪出一次运行到底在哪里跑偏了。 | 独立运行（参数：`<database.db> <agent-id>`） |
| [`self_healing_agent.py`](../examples/self_healing_agent.py) | 一个 agent 在冒险动作前先打 checkpoint，失败就回滚恢复（那套 Litany 循环）。 | 依赖模型 |

## Engram 与跨 agent 记忆 (Engrams & cross-agent memory)

| 示例 | 演练了什么 | 怎么跑 |
|---|---|---|
| [`memory_search.py`](../examples/memory_search.py) | 跨 agent 记忆库：一个 agent 写入知识，另一个 agent 把它捞出来。 | 独立运行 ✓ |

## 评测探针击杀闸门 (Eval-probe kill-gates)

| 示例 | 演练了什么 | 怎么跑 |
|---|---|---|
| [`lighthouse_trace_probe.py`](../examples/lighthouse_trace_probe.py) | 一条可证伪探针（probe）端到端跑通：一道形状闸门（shape gate）登记为 *不予受理* → VOID，而一道可证伪闸门则把坏掉的运行打成 REJECT、把修好的版本打成 ACCEPT。整个跑在 `Bene(":memory:")` 上，自带一切、不依赖外物。 | 独立运行 ✓ |

## Shared-log 协同与多 agent (Shared-log coordination & multi-agent)

| 示例 | 演练了什么 | 怎么跑 |
|---|---|---|
| [`shared_log_coordination.py`](../examples/shared_log_coordination.py) | 那条只增不改的协同日志：跨 agent 的 intent → vote → decide → act 协议。 | 独立运行 ✓ |
| [`safety_voting.py`](../examples/safety_voting.py) | 一道架在 shared log 之上、靠策略硬卡的安全闸门：冒险动作落地之前，先过人在环路（human-in-the-loop）加多 agent 共识这两道关。 | 依赖模型 |
| [`code_review_swarm.py`](../examples/code_review_swarm.py) | 扇出一群 reviewer agent，靠 shared log 把各自的发现攒到一处。 | 依赖模型 |
| [`parallel_refactor.py`](../examples/parallel_refactor.py) | 一大批 agent 并行重构，各自隔离，结果再合流。 | 依赖模型（示意性质 —— 读它就是为了抄那个套路） |

## 演化式 meta-harness 搜索 (Evolutionary meta-harness search)

`meta_harness_*` 这几个脚本，每一个都为一个不同的 benchmark 领域配种出一套 harness；全是依赖模型的（它们要跑一整套搜索循环）。它们共享同一副骨架 —— 播下一套 harness 火种，跨世代变异，再过一道击杀闸门（kill gate）探针把胜出者扶正。

| 示例 | 领域 |
|---|---|
| [`meta_harness_coding.py`](../examples/meta_harness_coding.py) | agent 式编程 |
| [`meta_harness_math.py`](../examples/meta_harness_math.py) | 数学推理 |
| [`meta_harness_support_tickets.py`](../examples/meta_harness_support_tickets.py) | 客服工单分流 |
| [`meta_harness_fraud_detection.py`](../examples/meta_harness_fraud_detection.py) | 反欺诈 |
| [`meta_harness_crm_campaigns.py`](../examples/meta_harness_crm_campaigns.py) | CRM 营销活动 |
| [`meta_harness_clv_prediction.py`](../examples/meta_harness_clv_prediction.py) | CLV 客户生命周期价值预测 |
| [`autogenesis_heldout_loop.py`](../examples/autogenesis_heldout_loop.py) | 留出集（held-out）晋升循环（闸门看不到测试集） |

## 研究实验室 (Research labs)

| 示例 | 演练了什么 | 怎么跑 |
|---|---|---|
| [`autonomous_research_lab.py`](../examples/autonomous_research_lab.py) | 一套多 agent 的研究工作流，全部编排在同一个 BENE 数据库上。 | 依赖模型 |
| [`multi_gpu_research.py`](../examples/multi_gpu_research.py) | 把研究扇出到多个本地模型端点上跑。 | 依赖模型 |

---

*独立运行的示例都已验证能针对一次干净安装以 0 退出码收尾；依赖模型的示例则需要在 `bene.yaml` 里配好一个 provider。来源：仓库里的 `examples/` 目录 —— 画廊里的链接会解析到 docs 站点上那份拷贝过来的脚本。*
