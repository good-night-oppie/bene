# 接入 BENE (Integrating BENE)

BENE 是垫在你现有的 Agent 框架**底下**的一层底座 —— 上面那层你爱用 LangGraph、CrewAI、AutoGen、smolagents、Letta，或者是你自己手撸的死循环，全随你高兴。这篇文档就是一张极其诚实的底牌图：哪些东西是你开箱即得的白嫖福利，哪些东西是得你自己捏着鼻子写胶水代码焊上去的。看懂这张图，你就知道这趟水到底有多深。

长话短说：**Agent 的跑圈引擎 (loop) 是拧钥匙就走的；剩下的其他功能全是一地散装的乐高积木。** BENE 给你提供了足以支撑一个写码 Agent 系统在 5 个生命周期里所需的硬核底层原语，但只有那个跑圈引擎是系统帮你串好的。其他的原语你得自己拿胶水去粘 —— 这里绝对没有那种一键打包全家桶的所谓 "适配器"。

## 拧钥匙就走 —— 默认开启，零胶水代码 (Turnkey)

| 阶段 | 什么是你什么都不干就能白嫖到的 |
|-------|----------------------------|
| **Agent 跑圈引擎 (Agent loop)** | 只要任务是在 `ClaudeCodeRunner` 里跑的（或者你把内核强行挂到了你自己的循环上），每绕一圈，系统就会极其冷血地砸下一个 tier-0 级别的踪迹印记 (trace engram)；不仅如此，它还会给每一次工具调用 (tool call) 都配一个专属的印记（里面记着 `tool_name`, `status`, `error_message`），外加那本只能往里塞不能改的只读事件流水账。嫌烦的话可以在跑的时候关掉：`emit_engrams=False` / `kernel.emit_engrams: false`。 |
| **锁定真凶 (Failure localization)** | 就因为跑圈引擎默认会给每个工具留下印记，所以你拿着 `bene failure localize <agent>` 去抓虫时，它能在**真实的运行现场**里，一眼揪出那个最早让系统开始崩盘的致命失误 —— 这玩意不用你开启任何开关，也不用你去手动伪造现场。（去查阅 [CLI 指令大黄页 (cli-reference.md)](#bene-failure-localize)。） |
| **只读盯盘 (Read-only inspection)** | 那个 `bene query` 命令在 SQLite 引擎那一层就被物理阉割成了纯只读 (`PRAGMA query_only`) —— 把它当成工具递给一头发疯的 Agent 都绝对安全。`bene ls` / `status` / `logs` / `read` / `search` 这堆命令全是在对着同一个文件读来读去。 |

## 自己动手丰衣足食 —— 硬核原语，但你得自己拼装 (Wire-yourself)

| 阶段 | 提供的底层原语 (Primitive) | 你得手写糊上去的胶水 |
|-------|-----------|--------------------|
| **炸机与抢救 (Fault)** (比单纯的锁定真凶更进了一步) | `bene.checkpoints` (拍快照 / 查差异 / 逆转时空), 污染截断 (pollution recovery) | 你得自己写代码去判断 *什么时候* 该拍快照，以及在你的循环里到底 *满足了什么烂摊子条件* 才触发回滚。 |
| **淬火防线 (Harden)** (也就是评测闸门) | `bene.kernel.eval` — 用 `Probe(name, [gate], fn).register(store, conn, baseline=...)` 把规则死死封进 sha256 签名里；然后用 `bene.kernel.evolve.promote(candidate, ...)` 去过堂审问 → 吐出 晋升 (ACCEPT) / 毙掉 (REJECT) / 废弃 (VOID) 的判决。你可以拿着 `bene probe run --json` 把它硬怼进 CI 流水线里 (遇到 REJECT/VOID 当场报错拦截) —— 详见 [如何手写一刀致命的探针 (probe-authoring.md)](probe-authoring.md)。 | 你得自己写个 Python 脚本，去定义那个探针 (`Probe`)、把它注册进去、并在你的 CI 或者晋升节点上去调 `promote()` (或者跑 `bene probe run`)。 |
| **技能库 (Skills)** | 技能存储系统 + 技能蒸馏机制 (distillation) | 你得自己写个引擎去把那些跑过的印记蒸馏成技能，并且自己写逻辑去决定到底哪个技能值得留下来。 |
| **吃数据的进化 (Data)** (靠数据喂出来的进化路线) | `bene.kernel.evolve` — 包括 `mh search` (元引擎搜寻), genome (基因组) / 帕累托边界 (Pareto), 以及带着闸门的晋升通道 | 你得完全靠纯 Python 去写提纯 (distill) 和繁育 (breed) 的驱动引擎；目前这头和那头之间是断层的，得靠你手动搭桥。 |
| **绝对不重样的落地 (Atomic completion)** | [事务级落地方案 (Atomic completion recipe)](recipes/atomic-completion.md) — 在一个极其简陋的 SQLite/JSONL 日志文件上，做到不管怎么重试都绝对不重复的落盘机制 | 把这套跟平台无关的黑科技抄进你自己的事件日志系统里；这里压根就没有 Temporal 什么事。 |

### 用户接盘时必踩的三个胶水坑

1. **必须纯手敲的 Python 驱动代码 (探针 / 提纯 / 繁育)** —— 这套评测、蒸馏和进化的底座全是给代码调用的函数库，根本没有那种在终端敲一句就能一键跑通的流水线 (CLI pipelines)。你得在自己的代码里去调用它们。
2. **没人管的自动晋升 / 神经可塑性定时器** —— `AutonomyPolicy.auto_promote()` 这玩意是确实存在的，但你必须显式开启（它靠着信任度和探针把等级从 L0 提到 L3；**但 L4 这个生杀大权永远且只能攥在活人手里**）。你得自己去定个闹钟告诉它什么时候跑；没人会帮你自动调度。
3. ~~**把翻车现场的元数据重新塞回去**~~ —— **这坑已经被填平了，不用你管了。** 在 0.30 版本的引擎升级之前，用户还得自己把工具报错的结果包装成印记元数据重新塞回去，那个实盘的 `localize` 抓虫命令才能用。现在的引擎已经学会了每次调用完工具就自己吐一个 tier-0 的印记，所以现在的实盘跑完直接就能拉出来剖尸抓虫。

## 0.30 版内核手术到底改了什么

这批是在内核层面对运行时 (runtime) 做出的修复（虽然你在包管理器里看到的版本号还是 `0.2.0`；这一节只是为了在文档门户里给这些改动一个交待）：

- **`bene failure localize` 现在真的能在一地鸡毛的实盘里抓虫了** —— 引擎现在学乖了，每一次从工具里爬出来，都会甩下一个 tier-0 的印记 (`tool_name` / `status` / `error_message`)。这就意味着 "跑一遍留一地印记 → 拿着 localize 去翻印记找死因" 这条链条在全链路上被彻底走通了，再也不用像以前那样靠人工去伪造那些测试用的印记了。
- **`bene query` 被从底层阉割成了纯只读** —— 靠着底层的 `PRAGMA query_only` 死死按住的。哪怕你拿个带着 `WITH … DELETE` 的 CTE 嵌套，或者是用注释把写命令伪装起来，都绝对骗不过底层的封锁线；任何试图搞破坏的写操作都会当场挨一记 `PermissionError` 耳光。

## 顺藤摸瓜

- [如何手写一刀致命的探针 (probe-authoring.md)](probe-authoring.md) — 别写那种永远不会翻车的假测试，去写一个真的能把烂代码就地正法的 "击杀闸门 (kill gate)"，然后拿 `bene probe run --json` / `bene probe ls --check-admissible` 把它粗暴地焊进你的 CI 里。
- [事务级落地方案 (Atomic completion recipe)](recipes/atomic-completion.md) — 仅仅用一个白开水一样的 SQLite/JSONL 文件，就能做出绝对不丢、绝对不重的落地效果 (没有 Temporal 的魔法)；这也是上面提到的 炸机/数据 胶水层的标准答案。
- [CLI 指令大黄页 (cli-reference.md)](cli-reference.md) — 字典一样的指令大礼包，每条底下都附带了验证结果。
- [深层架构 (architecture.md)](architecture.md) — 扒一扒印记阶梯 (engram ladder)、击杀闸门 (kill gate) 和信任度账本 (trust ledger) 是怎么在一个极其寒酸的 SQLite 文件里和平共处的。
- [v0.3 路线图大饼 (design/v0.3-roadmap-spec.md)](design/v0.3-roadmap-spec.md) — 去看看这套系统里到底还有多少需要你亲手去糊的烂摊子，以及我们画饼什么时候会把它们解决。
