# BENE 2.0 — 内核施工图纸 (Kernel Spec - buildable)

这是 `bene/kernel/` 模块的落地契约。第 4–8 期工程必须严格按这套图纸施工；任何偏离都必须在同一个 commit 里把这份文档改掉。老规矩从 `bene/schema.py` 继承：主键一律用 TEXT 存 ULID，`created_at` 默认值一律走 ISO-8601 格式 `strftime('%Y-%m-%dT%H:%M:%f','now')`，枚举用 CHECK 约束卡死，建表一律带 `IF NOT EXISTS`，有用的地方建部分索引。所有的写操作全得走底层存储层，严格遵守 `bene/core.py` 里的 sqlite3 连接纪律 (必须开 WAL 模式)。

---

## 1. V2 数据库结构 (只追加不修改的违建 — `bene/kernel/schema_v2.py`)

```sql
-- ============ 印记底座 (ENGRAM SUBSTRATE) ============
CREATE TABLE IF NOT EXISTS engrams (
    engram_id     TEXT PRIMARY KEY,                 -- ULID 主键
    kind          TEXT NOT NULL CHECK (kind IN
                  ('trace','episodic','semantic','procedural','strategic',
                   'eval','experiment','trust','pollution','intervention',
                   'proposal','spec','report')),
    tier          INTEGER NOT NULL DEFAULT 0 CHECK (tier BETWEEN 0 AND 4),
    title         TEXT NOT NULL,
    content_hash  TEXT,                              -- 指向碎肉块存储 (blob store) 的指针 (如果数据极小可以直接存 inline，这个字段可以为空)
    inline_body   TEXT,                              -- 给极小的数据包 (< ~4KB) 准备的内联存储
    metadata      TEXT NOT NULL DEFAULT '{}',        -- 存 JSON
    provenance    TEXT NOT NULL,                     -- 存 JSON: {"agent_id": ...} 或者 {"system": "<origin>"} — 强制要求！在 EngramStore.append 里死卡
    agent_id      TEXT REFERENCES agents(agent_id),  -- 如果跟特种兵有关，就在这挂钩
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    superseded_by TEXT REFERENCES engrams(engram_id) -- 有了新版本之后，这个字段就会指过去 (只许追加的版本控制)
);
CREATE INDEX IF NOT EXISTS idx_engrams_kind   ON engrams(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_agent  ON engrams(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_tier   ON engrams(tier);
CREATE INDEX IF NOT EXISTS idx_engrams_active ON engrams(kind) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS engram_links (
    link_id     TEXT PRIMARY KEY,                    -- ULID 主键
    src_id      TEXT NOT NULL REFERENCES engrams(engram_id),  -- 子节点 / 派生出来的东西
    dst_id      TEXT NOT NULL REFERENCES engrams(engram_id),  -- 父节点 / 来源
    link_type   TEXT NOT NULL CHECK (link_type IN
                ('derived_from','consolidates','verifies','refutes','associates',
                 'supersedes','about_agent','gated_by')),
    weight      REAL NOT NULL DEFAULT 1.0,           -- 联想强度 (以后可塑性机制会来调这个值)
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    UNIQUE(src_id, dst_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_src ON engram_links(src_id);
CREATE INDEX IF NOT EXISTS idx_links_dst ON engram_links(dst_id);

CREATE VIRTUAL TABLE IF NOT EXISTS engram_fts USING fts5(
    engram_id UNINDEXED, title, body, tokenize='porter'
);  -- 这张表是由 EngramStore 在写数据时顺手维护的 (索引了标题 + 负载里的纯文本内容)。
    -- engram_id 被设成了 UNINDEXED (不分词，但保留内容)，这样搜索结果才能 JOIN 回主表。

-- ============ 兵器库与自主权阶梯 (CAPABILITIES & AUTONOMY) ============
CREATE TABLE IF NOT EXISTS capabilities (
    name            TEXT PRIMARY KEY,                -- 例如 'memory.writeback', 'evolve.promote'
    description     TEXT NOT NULL,
    autonomy_level  INTEGER NOT NULL CHECK (autonomy_level BETWEEN 0 AND 4),
    handler_ref     TEXT,                            -- 带点的模块路径，或者注册表令牌 (仅供参考)
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE TABLE IF NOT EXISTS autonomy_grants (
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    domain      TEXT NOT NULL DEFAULT '*',           -- 能力领域 ('*' = 全局权限)
    level       INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
    granted_by  TEXT NOT NULL,                       -- 谁批的权限：'human:<name>' | 'policy:<rule>'
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    revoked_at  TEXT,
    PRIMARY KEY (agent_id, domain)
);

-- ============ 审判注册表 (极其精简，判决书本身全压成印记) ============
CREATE TABLE IF NOT EXISTS probe_registry (
    probe_id      TEXT PRIMARY KEY,                  -- ULID 主键
    name          TEXT NOT NULL UNIQUE,
    gate_spec     TEXT NOT NULL,                     -- 经过键值排序的、极其标准的 JSON 闸门规格
    lock_sha256   TEXT NOT NULL,                     -- 给 gate_spec 上的 sha256 锁；敢动一下直接拒捕
    status        TEXT NOT NULL DEFAULT 'registered'
                  CHECK (status IN ('registered','admissible','inadmissible','retired')),
    subject_ref   TEXT,                              -- 被审判的对象 (印记 ID 或者模块名字)
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id        TEXT PRIMARY KEY,                  -- ULID 主键
    kind          TEXT NOT NULL CHECK (kind IN ('probe','evolution','consolidation','sweep')),
    probe_id      TEXT REFERENCES probe_registry(probe_id),
    verdict_engram TEXT REFERENCES engrams(engram_id),
    summary       TEXT NOT NULL DEFAULT '',
    metrics       TEXT NOT NULL DEFAULT '{}',        -- JSON 存指标
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_experiments_kind ON experiment_runs(kind, created_at);

-- ============ 内核版本控制 ============
-- 必须跟前朝那个永远不准碰的 schema_version 划清界限
CREATE TABLE IF NOT EXISTS kernel_schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
```

一共新建 8 张表 (7 张实体表 + 1 张虚拟表)。**绝不准用 ALTER 去动前朝留下的老表。** 搬家防爆盾：`ensure_v2(conn)` 这个函数必须保证跑多少次都不会炸 (幂等)；专门弄了一张 `kernel_schema_version` 表 (跟前朝那个连个组件列都没有、而且任何人都不准去碰的 `schema_version` 彻底分家) 来记录 V2 的演进。

## 2. Python API 签名 (签名即契约)

### 2.1 `bene/kernel/engrams.py`
```python
class EngramStore:
    def __init__(self, conn: sqlite3.Connection, blobs: BlobStore) -> None: ...
    def append(self, kind: str, title: str, payload: str | bytes, *,
               provenance: dict, parents: list[str] | None = None,
               link_type: str = "derived_from", tier: int = 0,
               agent_id: str | None = None, metadata: dict | None = None) -> str:
        """只许追加。如果 provenance 里查不到 agent_id 或者 system，当场抛出 ProvenanceRequired 异常。
        负载超过 ~4KB 扔进碎肉块存储 (blob store)；否则直接内联。自动把标题和文本扔进 FTS 倒排索引里。"""
    def get(self, engram_id: str) -> Engram: ...
    def payload(self, engram_id: str) -> bytes: ...
    def search(self, query: str, *, kind: str | None = None, tier: int | None = None,
               agent_id: str | None = None, limit: int = 20) -> list[Engram]: ...
    def lineage(self, engram_id: str, *, direction: str = "ancestors",
                max_depth: int = 10) -> list[Engram]:
        """顺着 engram_links 爬树 (BFS 广度优先)；方向选 {'ancestors' (祖先) 或 'descendants' (子孙)}。"""
    def promote(self, engram_id: str, *, new_tier: int, title: str,
                payload: str | bytes, provenance: dict) -> str:
        """做梦整合机制：在 new_tier 层造一条全新的印记，然后拉一根 'consolidates' 的线连回老家。
        绝对不准碰那个源印记一根汗毛。如果新级别比老级别还低或者平级，当场抛出 TierViolation 异常。"""
    def supersede(self, old_id: str, new_id: str) -> None: ...
    def link(self, src_id: str, dst_id: str, link_type: str, weight: float = 1.0) -> str: ...
```

### 2.2 `bene/kernel/bus.py`
```python
class EventBus:
    def __init__(self, journal: EventJournal | None = None) -> None: ...
    def subscribe(self, event_type: str, handler: Callable[[dict], None]) -> str: ...
    def unsubscribe(self, sub_id: str) -> None: ...
    def publish(self, event_type: str, payload: dict, *, agent_id: str | None = None) -> None:
        """同步分发，保证至少送达一次；某个听众 (handler) 崩溃了会被隔离开 (只打印日志，其他人继续跑)；
        如果连了前朝的流水账系统 (journal)，自动做一份镜像。"""
```

### 2.3 `bene/kernel/capabilities.py`
```python
class CapabilityRegistry:
    def register(self, name: str, *, autonomy_level: int, description: str,
                 handler: Callable | None = None, metadata: dict | None = None) -> None: ...
    def lookup(self, name: str) -> Capability: ...
    def list(self, *, max_level: int | None = None) -> list[Capability]: ...
    def dispatch(self, name: str, agent_id: str, /, *args, **kwargs):
        """这就是执法的死门禁：在调 handler 之前先跑一遍 AutonomyPolicy.check；
        胆敢越权 -> 当场抛出 AutonomyDenied，并且顺着事件大巴发一条负面信用印记。"""
```

### 2.4 `bene/kernel/eval/` (probe.py, gates.py, verdict.py)
```python
class Gate(TypedDict, total=False):
    name: str; description: str; metric: str; op: str  # 必须是 >=, >, <=, < 其中之一
    threshold: float; relative_to_baseline: bool

class Probe:
    name: str
    gates: list[Gate]
    def register(self, store: EngramStore, conn, *,
                 baseline: Any, subject_ref: str | None = None) -> str:
        """把极度标准化的闸门规格算出 sha256 锁，然后落盘到 probe_registry 里。
        接着立刻跑可采纳性自证 (这步直接揉在这里面了 —— 别去外面搞什么 baseline_self_test 接口)：
        拿基线数据去冲闸门；如果连基线自己都死不了 -> 标记成 'inadmissible' 并废弃 (VOID)。
        否则标记为 'admissible'。"""
    def run(self, subject: Any, baseline: Any, *, store, conn,
            subject_ref: str | None = None) -> Verdict:
        """重新算一遍锁；如果对不上 -> 直接抛出 LockTamperError 锁被动过 (拒绝干活)。
        拿着数据冲闸门 -> 算出 Verdict(ACCEPT|REJECT|VOID) 落盘成 'eval' 印记，
        并往 subject_ref 上拉一根 'verifies'/'refutes' 的线；顺手在 experiment_runs 里留个案底。"""

class Verdict:  # ACCEPT / REJECT / VOID + 每个闸门的详细死法，印记是它的肉身
    status: str; gate_results: list[dict]; engram_id: str
```

### 2.5 `bene/kernel/trust.py`
```python
class TrustLedger:
    """这是算出来的账本，绝不是靠嘴吹的。四个白纸黑字的信号源 (全被卡在 0..1 之间)：
    verification_coverage = (拿得出证据的活) / (吹牛干过的活)；
    audit_completeness   = (记了结果的拿兵器记录) / (总拿兵器记录)；
    checkpoint_discipline = (拍快照的次数) / (碰了危险兵器的窗口期数)；
    outcome_reliability  = 近期权重更高的成功率 (带有半衰期衰减)。
    composite = 加权平均 (权重配比必须在模块注释里交代得一清二楚)。"""
    def summary(self, agent_id: str, *, domain: str = "*") -> dict: ...
    def record(self, agent_id: str, signal: str, value: dict) -> str:  # 制造一条信任印记
    def eligible(self, agent_id: str, level: int, *, domain: str = "*") -> bool: ...
    def weighted_vote(self, agent_id: str) -> float:  # 供 shared_log 在圆桌会议上算选票
```

### 2.6 `bene/kernel/evolve/` (gepa.py, distill.py, genes.py)
```python
class Genome:           # 拆开的结构化基因：每个部位各自进化 (D7/AHE/ADOPT)
    components: dict[str, str]   # {'memory_policy','retrieval_policy','context_strategy','tool_config','prompt'}
    gene: StrategyGene | None
    scores: dict[str, float]     # {'quality','cost','tokens'}

class ReflectiveEvolver:
    def __init__(self, store: EngramStore, conn, *,
                 reflect_fn: Callable[[Genome, list[str]], dict[str, str]],
                 benchmark: Callable[[Genome], dict[str, float]],
                 frontier: GenomeFrontier | None = None,
                 feedback_fn: Callable[[Genome, dict[str, float]], list[str]] | None = None,
                 surrogate: Callable | None = None) -> None:
        """那个 reflect_fn 必须老老实实吐出 {"component", "new_text", "rationale"} — 也就是
        指名道姓要改哪个部位的结构化突变图纸 (这就是 ADOPT 论文里的精准分锅)。"""
    def run(self, seed: Genome, *, generations: int, population: int = 4) -> GenomeFrontier:
        """每一代的大逃杀流程：对着最惨的炸机现场反思 -> 抽出文本梯度 -> 精准突变对应部位
        -> (也许过一遍便宜的平替门禁) -> 上刑具跑基准测试 -> 更新帕累托边界。
        每跑一圈全得在 experiment_run 留案底；活下来的全变成 'strategic' 印记。"""

class GenomeFrontier:    # 帕累托边界上的不败金身集合；复用 bene/metaharness/pareto.dominates()
    def update(self, genome: Genome) -> bool: ...   # (千万别把它跟 metaharness 里的 ParetoFrontier 搞混了 ——
    def members(self) -> list[Genome]: ...          #  那是另一个老古董类)

def promote(candidate_engram_id: str, *, store, conn) -> str:
        """想要上位？拿着连着这哥们的 ('verifies')、并且盖了 ACCEPT 的 'eval' 印记来见我。
        要是拿不出，当场抛出 PromotionBlocked 拦截。成了就在档案上拉一根 'gated_by' 的线；
        最后把那份判决书的印记 ID 吐出去。[D3]"""

class TraceDistiller:
    def distill(self, trace_ids: list[str], *, analyst_fn: Callable) -> list[str]:
        """对着案发现场开刀出补丁 (成了：一遍过；搞砸了：必须吐出连着案发现场的死因证据链)
        -> 按出场频率做合并 -> 压进 3 层的金字塔 (规划/干活/打杂)
        -> 变成 tier-3 的印记，并且在它跟 **每一个** 贡献过血汗的案发现场之间拉一根 'consolidates' 的线。"""

class StrategyGene:      # 高密度控制黑话 (GEP)：匹配什么信号，该走几步，千万别干嘛 (avoid[])
    def encode(self) -> str: ...
    @classmethod
    def merge(cls, a: "StrategyGene", b: "StrategyGene") -> "StrategyGene": ...
```

### 2.7 `bene/kernel/memory/` (granules.py, retrieval.py, contextos.py, pollution.py)
```python
class GranuleStore:      # 踩在 EngramStore 头上的 0..3 级台阶
    def write_turn(self, agent_id: str, text: str, **meta) -> str: ...
    def consolidate(self, granule_ids: list[str], *, summary: str,
                    provenance: dict) -> str:   # 调 EngramStore.promote 走晋升通道
    def associate(self, a: str, b: str, weight: float = 1.0) -> str: ...

class AdaptiveRetriever:
    def query(self, agent_id: str, text: str, *, k: int = 8) -> RetrievalResult:
        """拿着新问题去翻以前的查询印记看脸熟；脸熟度 >= fast_threshold -> 走极速通道
        (掏缓存/只给 top-k)；看着眼生 -> 走慢速通道 (FTS 硬搜 + 顺着联想线去挖)。到底走了哪条路，
        全写在结果和查询印记里备查 (透明度第一)。"""

class ContextOS:
    def register_strategy(self, name: str, fn: PackStrategy) -> None: ...
    def select_strategy(self, signals: dict) -> str:   # 抄 AgentSwing 的套路选打包策略
    def assemble(self, items: list[dict], budget_tokens: int, *,
                 signals: dict | None = None, strategy: str | None = None) -> PackedContext:
        """哪怕撑死也绝不准超预算 (按字符数/4 算个大概，可插拔)。你得自己把零件喂进来
        ({"id","text","relevance"?})；至于怎么把整个 Agent 的杂碎全兜在一起 (按 agent_id 组装)，
        那是以后接 runner 时才干的活 (排期中)。最后必须吐出一张明细单 (manifest)：
        塞了什么 (included[])，扔了什么 (dropped[])，用的什么套路，估算占了多少词元。[透明度/D8]"""

class PollutionDetector:
    SIGNALS = ('repeated_failed_calls', 'error_rate_spike', 'contradiction_markers')
    def scan(self, agent_id: str, *, window: int = 50) -> PollutionReport: ...
    def recover(self, agent_id: str, report: PollutionReport, *, bene: "Bene") -> dict[str, Any]:
        """把线索从泥潭里榨干 -> 生造一条 'pollution' 污染印记 ->
        时间倒流，切回发疯前的那个快照 (这是调前朝的老接口，包了一层壳而已)
        或者干脆洗干净脑子重新投胎。然后满世界发大巴广播。最后吐出三个尸体袋：
        {"pollution_engram", "consolidated", "restored_checkpoint"}。[D9]"""
```

### 2.8 `bene/kernel/harness/` (autonomy.py, senses.py, sweeper.py, guards.py)
```python
class AutonomyPolicy:
    def grant(self, agent_id: str, level: int, *, domain: str = "*", granted_by: str) -> None: ...
    def check(self, agent_id: str, capability: Capability) -> bool:
        """拿着兵器过来查岗 (里面装着 .name/.autonomy_level，用来划拉是哪个领域的，再比大小)。
        如果特种兵在那个领域的 (最高权限级别) >= 这把兵器要的 (autonomy_level) 就放行；
        否则拒捕 -> 当场发一条负面信用印记。"""
    def guard(self, capability: Capability) -> Callable:   # 专门给 handler 函数包浆的装饰器

class SensesManifest:
    @staticmethod
    def generate(bene: "Bene", *, fmt: str = "json") -> str:
        """作战简报的切面：特种兵花名册+状态、兵器谱+权限等级、脑子里的技能、挂的记忆盘、
        刚才都干了啥、怎么唤醒它的话术。全从活着的库里现算。[永远不会发霉]"""

class DebtSweeper:
    SIGNATURES: dict[str, re.Pattern]  # 3 把刷子: 调试用的 print, 臭了的 todo, 死 import
    def scan_paths(self, paths: list[str]) -> SweepReport: ...
    def scan_agent_vfs(self, bene, agent_id: str) -> SweepReport:
        """扫出来的垃圾全拍成 'report' 印记；外面可以用 CLI 的 `bene sweep` 唤醒。
        至于那些大段重复的烂代码 (duplicated_block)，是用个滑动窗口去抠出来的
        (窗口大小 DUP_WINDOW 行)，不是拿正则去瞎匹配的。"""

class LoopGuard:
    def __init__(self, *, window: int = 20, repeat_threshold: int = 5) -> None: ...
    def observe(self, event: dict) -> Intervention | None:
        """盯着那帮翻来覆去干傻事 / 疯狂横跳的脑残 -> 赏一条 'intervention' 强行介入印记 +
        挂个回调 (默认是：强行塞一句反思笔记 + 打个挂号信标记)。用完就能拔掉的中间件。"""
```

### 2.9 命令行开疆拓土 (`bene/cli/main.py`)
全家桶：`bene probe ls|show`, `bene trust <agent_id>`, `bene experiments ls|show`, `bene senses`, `bene sweep` —— 每一个破指令都必须能接 `--json`。(绝对不允许搞什么 `probe selftest` 的子命令：可采纳性自证这事，早就直接锁死在 `Probe.register` 的娘胎里了。)

## 3. 打死不能破的铁律 (全被写死在第 4-8 期的测试套件里)

1. 往印记底座里写字，敢不带血脉来源 (provenance) 直接崩掉 —— 这里不收容黑户经验。
2. 晋升这事绝不准碰来源文件一根汗毛；级别这玩意，只能顺着 `consolidates` 那条红线往上爬。
3. 拿 2.0 去开 0.1.0 的老坟：跑完 `ensure_v2` 之后，前朝在 `sqlite_master` 里的那些骨架，连一个字节都不准掉。
4. 探针的闸门规格只要被动过手脚，它必须当场罢工 (LockTamperError)。
5. 探针的基线数据如果连它自己的闸门都冲不开，这种废品当场作废 (VOID)。
6. 调 `evolve.promote` 时，手里拿不出一张 ACCEPT 绿卡，当场死在 PromotionBlocked 上。
7. ContextOS.assemble 吐出来的包裹，不管你怎么塞，绝不准撑破预算 (必须有属性测试兜底)。
8. 一个挂着 L1 狗牌的菜鸟敢去摸 L3 的兵器，当场抛出 AutonomyDenied，**并且** 必须在它档案上留一条查账的信用印记。
9. 搞进化的大管家和拿着探针的裁判，在物理上绝不能共用一套脑子 (必须隔离裁判 —— AEVO 的血泪教训)。去查这个测试：`tests/kernel/test_hardening.py` 里的 `test_verifier_isolation_evolver_cannot_mint_verdicts`。
10. 内核全家桶的每一条 CLI 指令，都必须能吞吐 `--json`。

## 4. 搬家计划表 (前朝那堆烂摊子该怎么死)

| 那个倒霉的老模块 | 下场 | 哪一期动手 | 判词 |
|---|---|---|---|
| core.py (VFS 虚拟文件系统) | 留任 | — | 内核依然从它身上碾过去；一个字不用改 |
| schema.py | 留任 | — | v2 那些违建全搭在 kernel/schema_v2.py 里 |
| blobs.py | 留任 | 4 | 印记肉身的垃圾场 |
| events.py | 留任 | 4 | 大巴直接给流水账开个镜像 |
| checkpoints.py | 留任 (套壳) | 7 | 污染抢救队就是调它的接口；它的本体一个字不准动 |
| isolation.py | 留任 | — | |
| memory.py | 改道 | 9 | 写的时候顺手在印记阶梯上留个影 (开 `attach_kernel(memory=...)` 就能上车；用不着配什么狗屁开关) |
| skills.py / skills_discovery.py | 改道 | 9 | 全给倒影进肌肉记忆里去了 (已上线)；至于技能变老、退休那套生死轮回，排在后面 (计划中) |
| shared_log.py | 改道 | 9 | 投票时看信用分下菜碟 |
| intake.py | 留任 | — | |
| ccr/ (引擎, 兵器, 并行苦力, 提示词) | 改道 | 9 | 把 ContextOS 挤水机 / 防鬼打墙中间件 / 读感官报告的套路，全给它挂上去 (计划中)；内核原语现在全是单挑干活的 |
| router/ (梯队, 镖局, agent_sdk, 初诊大夫, vllm_client, context.py) | 留任 | 9 | 全留着；至于把 router/context.py 给揉进 ContextOS 里的脏活，以后再说 (计划中) |
| mcp/server.py | 改道 | 9 | 内核管家的命门全露在 CLI 里 (`bene probe/trust/experiments/senses/sweep`) 和 UI 里 (/api/engrams, /api/trust)；等有空了再去打两把 MCP 的兵器 (计划中) |
| cli/ | 改道 | 5,8,9 | 开全家桶；洗一波脸 |
| ui/ | 改道 | 9 | 翻印记面板 + 查成分账本 |
| obsidian/ | 留任 | — | |
| metaharness/ | 改道 | 6,9 | 进化大管家去蹭饭；pareto.py 继续发光发热；蒙眼裁判被抓去审探针了 |
| benchmarks/ (里面空空如也) | 留任 (纯粹是为了占坑的命名空间) | 10 | 留着以后给那些实干的业务包让路，省得引用路径全炸了 |
| storage/ | 留任 | — | 内核写字全得从它身上碾过去 |
| runtime/ | 留任 | — | |
| temporal/ | 留任 | — | 把 KAOS 摁在地上摩擦的底气全靠它，必须留着 |
| integrations/ (空巢) | 留任 (纯粹是为了占坑的命名空间) | 10 | 留着以后给那些实干的业务包让路，省得引用路径全炸了 |
```
