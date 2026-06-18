# 经验技能库 (Skill Library)

如果项目里的某个 agent 趟出了一条极其稳妥的执行套路，那么跟在它后面的所有 agent 都能直接把这套路翻出来、填上参数、直接开跑 —— 根本不用每次都在冰冷的零起点重新发明轮子。

> **一句话看懂：** 所谓的 skill，就是一个挖了 `{param}` 参数坑的 prompt 模板。项目里的任何 agent 都能通过全文检索把它挖出来，填上自己的业务变量，并且在用完之后给它打个分。

所有数据都不会离开你的机器半步。整个技能库的实体就是潜伏在项目数据库里的两张 SQLite 数据表 (`agent_skills` 连同它的全文索引表) —— 把那个 `.db` 文件拷走，这些技能也就跟着走遍天下了。

## Agents 究竟怎么用它

记忆 (Memory) 负责记下**曾经发生了什么**；而技能 (Skill) 负责传授**下次该怎么做**。如果没有技能库，好不容易摸索出的文本分类套路、异步报错排查手法或是 API 响应清洗格式，都会在 session 结束时烟消云散。而有了它，工作流变成了这样：

1. **先搜为敬 (Search first)。** 在动手之前，agent 会先跑一把 `skill_search "任务描述"` (或者在终端敲 `bene skills search`)，看看前人是不是早就把这个问题给干穿了。
2. **渲染套壳 (Render)。** 拿到模板后，用 `skill_apply` 把当下任务的真实参数塞进模板里的 `{param}` 占位符里。
3. **干活，然后打分 (Work, then grade)。** 任务结束后，agent 必须通过 `skill_outcome` 如实上报是成功还是搞砸了；`use_count` 和 `success_count` 这两个计数器会把重复使用的战绩，硬生生砸成清晰可见的可靠度背书。
4. **反哺入库 (Contribute back)。** 如果一个 agent 趟出了一条极其值得传家的崭新套路，它会用 `skill_save` (或者敲 `bene skills save`) 把它封存进库里。

## 在黑框框里直接操纵

你可以用 `bene skills` 命令行覆盖绝大多数的生命周期操作 —— 保存、寻找、罗列、渲染以及删档。（只有打分不能在命令行里做：你必须通过 `skill_outcome` MCP 工具或者 Python 里的 `SkillStore.record_outcome` 来入账。另外注意：跑 `skills save --agent <id>` 时传入的 `source_agent_id` 必须是指向一个已经存在的 agent —— 乱填的 ID 会被外键约束当场拍死 —— 当然，你要是想存全局通用的公共 skill，把这个参数略过就行。）

```bash
# 保存一个技能
bene skills save \
  --name ensemble_classifier \
  --description "Improve classification accuracy with ensemble voting" \
  --template "Use {n_models} models with {voting} voting on {task}." \
  --tags classification,ensemble

# 动手干活前先查查
bene skills search "classification accuracy"
bene skills search "async error handling" --tag python

# 拉出所有技能 —— 自动按热门程度 (使用次数) 排序
bene skills ls --order use_count

# 往模板里塞参数并渲染出来
bene skills apply 3 -p n_models=3 -p voting=majority -p task="sentiment"

# 删掉
bene skills delete 3
```

## 让搜索结果像手术刀一样精准

底层搜寻引擎是自带 porter 词干提取的 SQLite FTS5。有四个字段被卷进了索引的绞肉机里：

- `name` — 那个 snake_case 风格的技能代号
- `description` — 它的使命是什么，以及它到底该用在什么节骨眼上
- `tags` — JSON 数组，里面的词条会被当成普通文本一样分词切片
- `template` — 就是 prompt 模板的真身，连带着里面的占位符名称

搜索结果默认靠 BM25 (词法相关度) 排名。加上 `--rank weighted`，系统就会用胜率来重新洗牌 —— 计算公式是 BM25 乘上威尔逊下限胜率 (Wilson-lower-bound success rate)，再叠加上时间衰减因子。所有这些战绩数据都来自 `skill_outcome` 录入的账本。这套机制直接保证了那些**久经考验极其靠谱的 skill，会残暴地碾压那些字面很像但老是翻车的花瓶**。任何 FTS5 能听懂的咒语，在这都能跑：

```bash
bene skills search "ensemble accuracy"        # 词干提取搜索
bene skills search '"gradient clipping"'      # 必须一字不差的短语搜索
bene skills search "classification NOT naive" # 否定词过滤
bene skills search "classif*"                 # 前缀通配符
```

## 在 Python 里调用

在代码里，`SkillStore` 提供了等价的火力网：

```python
from bene import Bene
from bene.skills import SkillStore

bene  = Bene("project.db")
sk    = SkillStore(bene.conn)
agent = bene.spawn("classifier-dev")   # source_agent_id 是个外键 → 必须是个真实存在的 agent

# 趟出一条可靠的血路后，赶紧存进库里
sid = sk.save(
    name="ensemble_classifier",
    description="Improve classification accuracy with ensemble voting",
    template=(
        "Implement a {n_models}-model ensemble for {task}. "
        "Use {voting} voting. Tune the decision threshold to {threshold}."
    ),
    tags=["classification", "ensemble", "accuracy"],
    source_agent_id=agent,
)

# 在碰类似任务前，先翻翻找找
hits = sk.search("classification accuracy")
for s in hits:
    print(s.name, s.params())  # → ['n_models', 'task', 'voting', 'threshold']

# 塞参数渲染出成品 prompt
skill = sk.get(sid)
prompt = skill.apply(
    n_models="3",
    task="sentiment analysis",
    voting="majority",
    threshold="0.5",
)

# 打分入账，让它的可靠度累积发酵
sk.record_outcome(sid, success=True)

# 拉出技能榜单 —— 直接按可靠度排座次
reliable = sk.list(order_by="success_count")
```

## 将它直接怼进 Claude Code 或是 Cursor

5 把 MCP 专武，直接把这座武器库敞开在任何通过 MCP 接入的 agents 面前：

| MCP Tool | 用途 |
|---|---|
| `skill_save` | 连着代号、简介、模板和标签，把一个新技能拍进库里 |
| `skill_search` | 直接打穿所有技能的 BM25 全文检索 |
| `skill_apply` | 往一个技能模板里塞参数并渲染出成品 |
| `skill_list` | 罗列技能清单，还能挂上 tag/agent/排序 的过滤网 |
| `skill_outcome` | 给刚才用过的技能打分 (成败判定) |

### 一段实战演示

```text
# 准备动手搞重构前：
skill_search("refactoring async python")

# → 挖出了 7 号技能: "async_refactor"
# → 模板长这样: "Refactor {module} to use {pattern}. Key steps: {steps}"

skill_apply(skill_id=7, params={
    "module": "auth.py",
    "pattern": "async/await",
    "steps": "1. replace callbacks, 2. add error boundaries, 3. update tests"
})

# 干完这票之后：
skill_outcome(skill_id=7, success=True)
```

## 到底该记在 Skill 里还是 Memory 里？

这两座库都是全局共享的，底层也都被 FTS5 引擎驱动；它们的分野，在于它们存放的认知维度截然不同。

| | Memory (记忆) | Skill (技能) |
|---|---|---|
| **到底存啥** | 既成的事实，观察到的现象，跑出来的战果 | 办事的流程，制胜的策略，可复用的模板 |
| **例子** | "上了 ensemble 投票后准确率飙到了 87%" | "想要拉升准确率：用 {voting} 策略对 {n} 个模型执行..." |
| **何时使用** | agent 刚干完一票活准备收工时 | agent 刚摸索出一条极其稳妥且能复用的套路时 |
| **打捞方式** | 基于内容正文的 FTS5 搜索 | 针对名字、简介、标签和模板的 FTS5 搜索 |
| **底层表名** | `memory` | `agent_skills` |

如果这玩意儿的价值就在于**陈述一个既成事实** —— 比如 "这套模型在 X 数据集上跑了 87%"，哪怕它根本没法拿来执行第二次，它也依然值得被记住。各种底细、报错死因和跑出来的冰冷数字，统统归 **memory**。

如果这玩意儿的价值在于它的**流程机制** —— 也就是一记可以交由下一个 agent 依葫芦画瓢、填空后直接抄作业的杀招套路，而不是每次都得从零推演一次，那就丢进 **skill**。

## 它的骨相到底长什么样

统共就两张表：`agent_skills` 存放血肉，`agent_skills_fts` 负责搜寻。

```sql
CREATE TABLE agent_skills (
    skill_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    template        TEXT NOT NULL,          -- {param} 占位坑
    tags            TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    source_agent_id TEXT REFERENCES agents(agent_id),  -- 外键; 必须是个活着的 agent，如果想存全局通用 skill 就把它置空
    use_count       INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- FTS5 外挂索引引擎，把名字、简介、标签和模板本体统统卷进去查
CREATE VIRTUAL TABLE agent_skills_fts USING fts5(
    name, description, tags, template,
    content='agent_skills', content_rowid='skill_id',
    tokenize = 'porter unicode61'
);
```

## 这套设计的渊源

技能库 (Skill Library) 是下面这篇论文中 "外部化 (Externalization)" 框架里 **Skills (技能)** 轴向的具象化实现：

> "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering"
> Zhou, Chai, Chen, et al. (2026)
> [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)

这篇综述划定了四条向外部环境借力的轴线，而 BENE 在这四条轴上全部钉上了落地的实体系统：

| 轴向 | BENE 里的具象实体 |
|---|---|
| Memory (记忆) | `MemoryStore` — 跨 agent 共享的 FTS5 情景记忆库 |
| **Skills (技能)** | **`SkillStore` — 跨 agent 共享的 FTS5 程序化模板库** |
| Protocols (协议) | `SharedLog` — 基于 LogAct 的意图/投票/决议总线 |
| Harness (脚手架) | `MetaHarnessSearch` — 全自动的演化策略寻优器 |
