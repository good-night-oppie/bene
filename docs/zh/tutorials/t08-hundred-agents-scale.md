# 百狼夜行：单库调度，零事故交付

这篇教程将带你见识如何一口气把 BENE 裂变出几百只 agent —— 一只 agent 盯死一个文件 —— 并且在跑完之后，你得到的是确凿的 "没有任何东西被搞砸" 的铁证，而不是虚无缥缈的侥幸。这套打法来自一次真实的实战记录：847 只 agent 在 8 分 47 秒内，把包含 847 个文件的 Python 2 屎山强行提拉到了 Python 3.11；所有没跑通测试的改动全被当场掐死并自动回滚；整个大行动结束后，所有的罪证和战功，全被整整齐齐地封印进了一个能用纯 SQL 拷问的 SQLite 文件里。

> **一条指令撒出 847 只隔离在沙盒里的 agent；809 只凯旋，31 只因为测试挂了原地回滚，没有 1 行带有回归 Bug 的代码混进代码库 —— 而这份全景审计报告，不过就是一个你能随手 `cp` 拷走的 214MB 的 `bene.db`。**

*17 个批次，847 只 agent：809 只凯旋，31 只自裁重置，7 只举白旗交给活人处理，0 事故侵入主干 —— 并且，靠着黑科技省下了 245 万个根本没必要发送的 token。*

---

## 战报速览

先上干货数据，再讲背后故事。这是这 847 只 agent 最终的下场：

```text
结局          数量    占比
-----------  -----  -----
成功 (succeeded)    809    95.5%
回滚 (rolled_back)  31      3.7%
投降 (failed)       7       0.8%
总计 (total)        847   100.0%
```

再看看这种丧心病狂的并发到底能替你省下多少命：

```text
流派                        耗时      备注
--------------------------  --------  -------------------------
BENE 并发流 (847 匹狼)        8分 47秒   分 17 批次，每批 50 只
传统单线 AI 苦力 (1 只)       约 4.2 小时  毫无并发可言
纯正血肉工程师 (估算)       约 18 天    按 1 文件/半小时 × 847 算
```

能做到 "零事故漏网"，靠的绝对不是运气好，而是有两道死死咬住底线的闸门。31 只 agent 亲眼看见自己的改动没跑通测试，当场就把自己的沙盒时光倒流回了动手前的快照状态。而有将近 180 起本该发生的惨剧，更是直接被扼杀在了摇篮里 —— 因为中央枢纽 (hub) 把先头部队踩雷的死法当场大喇叭广播了出去，让后面那群正准备碰同样代码的兄弟提前避了坑。我们也要坦诚对待最后那 7 个投降的家伙：它们碰到的文件里含有根本没法安全机翻的 Python 2 奇技淫巧，所以这些 agent 非常聪明地选择了停手，把文件标红，原封不动地留给了活人工程师来定夺，而不是像个愣头青一样去硬猜。

---

## 为什么 "物理隔离" 才是这一整套戏法的阵眼

如果只派几只 agent，"为每只 agent 准备独立沙盒" 听起来像是个华而不实的噱头。但当你把规模拉爆到几百只的时候，这玩意儿就是挡在你和 "代码库被悄无声息地搞烂" 之间的唯一一道护城河。共享状态下的惨剧通常是这么发生的：一只 agent 正在狂改 `utils/compat.py`，而另一只 agent 刚好在读这个文件以决定自己的改法 —— git 不会报冲突，一切看似岁月静好，但里面其实已经烂透了，几天后它只会化作一堆根本找不到源头的测试报错。共享上下文在 token 层面也是同一种绝症：那些让 N 只 agent 共享同一个上下文窗口的框架，不仅要白白烧掉大概 N 倍的 token 钱，而且根本没有换来任何智商上的加成。

BENE 给出的解法是降维打击。每一只 agent 都拥有一个私有的、由 SQLite 驱动的虚拟文件系统 (VFS) —— 纯基于内容寻址，每一次写入都有流水账记录，每一次快照都极其廉价。没有任何东西会因为意外而被共享；而 agent 之间那些真正需要互通有无的东西 (比如踩坑经验、去重的二进制块)，则会通过专门定制的接口，极其克制地进行同步。

---

## 放狼：一个文件盯一只

整个漫天撒网的行动，其实就只是一次读取清单文件的 CLI 调用。每只 agent 领走一个文件，生拽硬拉升到 Python 3，跑一发测试，如果全绿就拍快照存档，如果有红的就当场自尽回滚。起手指令就是 `bene parallel spawn`。

```bash
# 按名单一次性放出 847 匹狼
bene parallel spawn \
  --manifest migration-manifest.txt \
  --task "升到 Python 3.11，跑测试，如果过了就存档" \
  --model claude-sonnet-4-6 \
  --batches 17 \
  --batch-size 50

# [bene] 读懂了名单: 847 个文件
# [bene] 正在投放第 1/17 批空降兵 (代号 1-50)...
# [bene] 正在投放第 2/17 批空降兵 (代号 51-100)...
# ...
# [bene] 所有 847 匹狼已在 00:00:17 秒内投放完毕
# [bene] 正在狂奔...
```

撑起这条指令的，是背后那份极其简练的 `bene.yaml`：

```yaml
# bene.yaml
project: py2to3-migration

agents:
  model: claude-sonnet-4-6
  isolation: logical
  checkpoint_on_success: true        # 过了测试就存档
  rollback_on_test_failure: true     # 测试挂了就自尽重来

compression:
  aaak_level: 5          # 极端榨干模式 — 摘要的 token 数直接砍掉 95%
  blob_dedup: true       # 全局开启 SHA-256 + zstd 终极去重

parallelism:
  max_concurrent: 50     # 掐死在 WAL 模式能舒服抗住的并发上限
  batch_size: 50
  retry_on_timeout: 2

hub:
  enabled: true          # 唤醒 CORAL 蜂巢网络
  min_confidence: 0.85
  broadcast_on_discover: true
```

其中两项配置是镇山之宝。`aaak_level: 5` 开启了 BENE 里最丧心病狂的上下文压缩黑魔法 —— 能生生把每只 agent 的记忆摘要砍掉 95% 左右，下面有实盘数据的硬核证明。而 `max_concurrent: 50` 则是把同一时刻疯狂写入的疯狗数量，死死按在了 SQLite WAL 模式绝对不会崩溃的安全线里；刚才空降时那 17 个批次，就是被这个上限给逼出来的。

---

## 止损：即使翻车，也绝不溅血

在 847 匹狼里，有 31 匹改完代码后一跑测试，当场就挂了。如果你用的是那种几个 agent 混用的共享文件系统，你现在已经该满头大汗地去理清这团乱麻了 —— 因为哪怕你只想回滚一个文件，都极大概率会把隔壁那哥们刚写到一半的代码给搅黄了。但在 BENE 里，抢救的动作不过就是把这一个私有 VFS 的时间拨回上一刻而已：不需要去锁全局大盘，也绝不会打扰任何其它正在埋头苦干的兄弟。

来看一眼 31 号阵亡名单里的老哥，代号 312，是怎么处理 `db/connections.py` 的：

```text
[agent-312] db/connections.py  强升 Python 3 完毕
[agent-312] 开跑 pytest...
  挂了 FAILED tests/test_db.py::test_connection_pool_size
  挂了 FAILED tests/test_db.py::test_reconnect_on_timeout

  2 个挂了, 23 个绿了

[agent-312] 嗅到测试翻车的气味 — 正在把时光倒流回动手前的快照
[agent-312] 正在重置 VFS 时空至: pre-migration-312
[agent-312] 时光倒流完毕，耗时 0.08 秒
[agent-312] status: rolled_back (已自裁回滚)
[agent-312] 死亡录像已存档: {
  "agent": "agent-312",
  "file": "db/connections.py",
  "failures": ["test_connection_pool_size", "test_reconnect_on_timeout"],
  "failure_pattern": "timeout_kwarg_renamed",
  "rollback_time_s": 0.08,
  "other_agents_affected": 0
}
```

这段遗言里只有两个数字最重要。那个 `时光倒流完毕，耗时 0.08 秒` 意味着它的 VFS 连十分之一秒都没到就恢复了出厂设置。而那个 `other_agents_affected: 0 (伤及无辜: 0)` 则是在向你拍胸脯保证，剩下的 846 匹狼根本连个响都没听见。

<div class="callout" style="background:#12121a;border-left:3px solid #6c5ce7;padding:1rem 1.4rem;margin:1.5rem 0;border-radius:0 8px 8px 0">

**硬核底线：** 一次倒流恢复，永远只会在这一只 agent 自己的 SQLite 泥潭里折腾 —— 绝不去动你电脑硬盘上的文件，绝不设全局锁，绝不碰任何其他 agent 的 VFS 结界。从架构上焊死了：一只踩雷狗的爆炸半径，只有它自己。

</div>

顺带瞥一眼那个 `failure_pattern` 字段 —— 里面写着 `timeout_kwarg_renamed`。这串东西，马上就要被扔进中央枢纽 (hub)，去救其他兄弟的命了。

---

## 吹哨：一家翻车，二十三家避雷

在 BENE 的世界里，一次自裁回滚绝不是简单的毁尸灭迹 —— 它是一份用血写就的避坑指南。从挂掉的测试里提取出来的死因，会立马被甩给 CORAL 中央枢纽 (就是那个所有 agent 共享的协调黑板)；那些手里正捏着类似文件还没来得及动手的特种兵们，看到黑板上的警告后，会直接在动刀子前把这个坑给绕过去。

这波大迁移里最值钱的一条避坑警告叫 `none_guard_before_has_key`：

```text
[hub] 从 312 号烈士的骨灰里扒出了一条全新的死法
  坑名 (pattern): none_guard_before_has_key
  实锤度 (confidence): 0.91
  踩雷条件 (trigger): 当字典可能为 None 时，去瞎调 dict.has_key()
  避雷针 (fix): 在强行换成 .get() 之前，先特么套一层 `if dict is not None`
  苦主 (source_failure): test_connection_pool_size, test_reconnect_on_timeout

[hub] 正在拉响大喇叭，向手里捏着类似代码的 23 位老哥通报...
  agent-089: db/session.py         → 收到，已防患于未然
  agent-134: db/pool_manager.py    → 收到，已防患于未然
  agent-201: cache/backend.py      → 收到，已防患于未然
  ...
  [23 匹狼已签收避雷指南]

[hub] 避雷针经受住了考验: 23/23 匹狼全部防穿透，在同类文件上 0 新增翻车
```

这帮家伙在这场战役里总共在黑板上贴了 12 种绝密死法。手里拿到了相关避坑指南的 agent，文件翻车率只有 3.8%；而那些没有指南护体的同类文件，翻车率高达 22.1%。把这笔账算到被大喇叭罩住的那 210 个文件头上，相当于硬生生帮你拦截了 38 起测试惨案；如果再把其他死法也一起算上，估计总共拦下了差不多 180 起事故。

```text
扒出来的死法                      12 种
听劝并避雷的狼                    147 匹 (各种死法的总和)
生生拦下的退化惨案 (预估)          约 180 起
没大喇叭护体时的伤亡率            22.1%
有大喇叭护体时的伤亡率             3.8%
```

这里面其实没什么玄学。所谓中央枢纽的避雷指南，不过就是一块格式化的高级共享内存：包含一个踩雷条件，一根避雷针，还有一个实锤度打分。收到这玩意的 agent 只是把它当成一句过来人的劝告，而不是什么必须强制执行的打补丁脚本 —— 这感觉就像是那个秃顶的资深老鸟走过你工位时随口点拨了一句。

---

## 抠门：压缩你的记忆摘要，但不偷工减料

![AAAK 压缩黑魔法示意图 — 上下文摘要 → 榨取锚点 → K-级极致压缩 → 扔给下一轮](compaction-flow.png)

AAAK (自适应锚点感知 K 级压缩，也就是 BENE 把 MemPalace 榨干后的魔改版)，会在每个回合之间，极其残暴地把 agent 背着的那坨上下文摘要 (context digest) 给榨干水分。如果你把强度开到 level 5，摘要拿回来的时候基本就只剩 5% 的骨架了。但它绝不会去碰当前的工作状态，所以无论你开不开压缩，agent 吐出来的代码变动都是一模一样的 —— 唯一变瘦的，只有你的账单。

**算一算单匹狼，跑一个回合的账：**

```text
这堆破烂             没开压缩时的分量  榨干后 (Level 5)  抠下来的钱
---------------  ------------  ---------------  ------------------
上下文摘要        6,100 tokens  305 tokens       省了 5,795 tokens (生砍 95%)
```

**再算总账 —— 847 匹狼，平均每人跑了 3.4 个回合：**

```text
狼群总计交锋回合数          2,880 轮
每回合从牙缝里抠出的代币      平均 ~850 币 (随文件大小波动)
总计人间蒸发的代币数        2,451,063 币
```

把所有的底牌都翻出来看看吧：如果不死开压缩，这活得烧掉你 858 万个推理 token；但现在，它只花了 613 万个 —— 那 245 万个 token，连网线都没碰过就直接不用发了。

```text
账单明细                      当个败家子 (不开 AAAK)  极致抠门 (AAAK L5)
--------------------------  ------------  ---------------------------
推理代币总消耗                 约 858 万币   约 613 万币
每轮背在身上的摘要             6,100 币      305 币 (缩了 20 倍！)
生生省下的代币                 —             2,451,063 币
交活的代码质量                 —             没打折扣 — 0 事故混入
```

![AAAK 压缩黑魔法杀伤力 — 各级压缩强度在 847 匹狼身上抠出来的代币总计](compaction-chart.svg)

丑话说在前面：level 5 是有损压缩，有些极其细微的上下文精髓会被生生抹掉。像这种单文件升级代码的任务，脑子不太好使也完全能应付。但如果你的特种兵必须带着极其复杂的逻辑链跨越很多个回合 —— 比如那种必须死死记住几十步前的分析结果才能做出判断的重构大阵仗 —— 赶紧老老实实把强度降回 level 3 或 4。反正也就是在 `bene.yaml` 里改一行字的事。

---

## 省地：847 个文件系统只占了 214MB 的坑

给 847 只特种兵每人发一个独立的文件系统，硬盘不就炸了吗？根本不会，因为 BENE 底下的那个 blob 存储库会在整个大盘里疯狂去重：所有的数据块都是按 SHA-256 寻址并被 zstd 往死里压的，所以哪怕有两只 agent 存了一模一样的文件，硬盘上也只占一份的坑。

如果我们算个死账，假设那 847 匹狼每人拿到了一份 250KB 大小的代码库拷贝，那你光存这些原始文件就得花掉 212MB —— 在整个池子里算下来大概得要 179GB 的空间，而且这还特么连一行日志、一点上下文 token、或者一份快照都还没开始算呢。但由于这帮家伙升代码时有海量的内容是完全重合的 (比如标准库导入、公共辅助函数、满天飞的样板代码)，这波跑下来，去重率直接飙到了 68%：

```text
算死账: 847 匹狼 × 平均 250KB = 212MB
靠 blob 去重省下的            = 144MB 被当场抹除
硬盘里真真切切存下的          =  68MB (+ 39MB 的快照数据)
                             = 总计 107MB (对比那个 212MB 的死账)
```

那些快照也是踩着同一套黑魔法上天的。它们只记差异 (diffs)，不存全量，并且它们的内容也全都在去重池子里 —— 所以，那 31 只自尽回滚的特种兵几乎没占什么额外的硬盘空间，因为它们那份 "翻车" 的代码其实跟它们回滚后那份 "正常" 的代码共享了绝大部分的数据块。行动结束：就这一个 214MB 的 SQLite 文件，装下了所有 847 匹狼的完整一生 —— 每一笔账，每一段录像，每一块血肉。

<div class="callout" style="background:#12121a;border-left:3px solid #6c5ce7;padding:1rem 1.4rem;margin:1.5rem 0;border-radius:0 8px 8px 0">

**硬核底线：** 狼群数量的膨胀，绝不会带来硬盘容量的核爆。相同的内容会被无情地压碎成一块，而且这些特种兵拿到的任务越雷同，去重效果就越变态 —— 在搞大重构或大迁移时，你可以闭着眼睛期待 60-70% 的去重率。

</div>

---

## 查账：把数据库按在地上拷问

我吹了这么多牛，你大可不必信。整场战役的尸山血海全是一堆老实巴交的 SQLite 数据，我上面放出的每一个狂言，都是一条 SQL 查询能当场戳穿的事。

那帮牲口最后死伤如何？

```sql
-- 揪出所有人的最终结局
SELECT status, COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / 847, 1) as pct
FROM agents
WHERE run_id = 'py2to3-migration'
GROUP BY status
ORDER BY count DESC;
```

```text
status       count   pct
-----------  -----   ----
succeeded    809     95.5
rolled_back  31       3.7
failed       7        0.8
```

那群倒霉蛋都是踩了什么雷挂掉的？又是死在哪个阵地上的？

```sql
-- 把所有带着死状的自裁记录全翻出来，按惨烈程度排个序
SELECT
  json_extract(notes, '$.failure_pattern') AS pattern,
  COUNT(*) AS occurrences,
  GROUP_CONCAT(file_path, ', ') AS affected_files
FROM vfs_events
WHERE run_id = 'py2to3-migration'
  AND event_type = 'restore'
GROUP BY pattern
ORDER BY occurrences DESC;
```

```text
pattern                        occurrences  affected_files
-----------------------------  -----------  --------------------------------
none_guard_before_has_key      8            db/connections.py, db/pool_manager.py...
print_function_side_effect     6            scripts/report.py, scripts/batch.py...
unicode_bytes_ambiguity        5            api/serializers.py, api/parsers.py...
iteritems_generator_consumed   4            core/registry.py, core/handlers.py...
...
```

抠门大法的成果到底有多少真金白银？

```sql
-- 代币省钱榜：查查 AAAK 到底替这群狼省了多少饭钱
SELECT
  SUM(tokens_uncompressed) AS total_uncompressed,
  SUM(tokens_compressed)   AS total_compressed,
  SUM(tokens_uncompressed - tokens_compressed) AS tokens_saved
FROM aaak_compression_log
WHERE run_id = 'py2to3-migration';
```

```text
如果败家怎么烧 (total_uncompressed)  抠完门后实际烧的 (total_compressed)  硬生生省下的 (tokens_saved)
---------------------------------  --------------------------------  -----------------------
4,949,663                          2,498,600                         2,451,063
```

那个中央大喇叭真的救了命吗？

```sql
-- 大喇叭防穿透榜：看看听广播前后的死伤率对比
SELECT
  pattern,
  before_broadcast_failure_rate,
  after_broadcast_failure_rate,
  agents_notified,
  estimated_regressions_prevented
FROM hub_pattern_stats
WHERE run_id = 'py2to3-migration'
ORDER BY estimated_regressions_prevented DESC;
```

这就是 "不可篡改的流水账" 和 "一堆破文本日志" 之间的天壤之别。你不是在用 grep 苦逼地捞线索；你是在对一份冷酷无情、有骨有肉的结构化台账进行 join (联表)、group (分组) 和 aggregate (聚合) —— 这 214MB 的铁证，走到哪带到哪，且永远属于你。

---

## 捅破天花板：这套东西会在哪里撑不住

我不喜欢吹那种毫无底线的牛逼，先把天花板亮给你看，你才能知道什么时候该收手。

**无论你派多少兵，这几条死理都不会变：**

- **VFS 物理隔离** — 纯粹的线性扩展，而且永远不会见顶。十匹狼跟一万匹狼没区别，没有任何一个人的文件系统需要排队等别人。
- **Blob 终极去重** — 比线性扩展还牛逼：盘子拉得越大，重复的破文件就越多，复用率就越炸裂，所以硬盘被吃掉的速度会被狼群的数量远远甩在后面。
- **AAAK 压缩黑魔法** — 纯粹的本地瞎折腾，按人头算线性消耗；狼群越大，给你省的饭钱就成堆地往上垒。
- **时光倒流 (回滚)** — 永远是一瞬间的事。上面那个 0.08 秒的复活神迹，是在 846 个战友正杀得天昏地暗时硬生生跑出来的，就算只有它自己玩，耗时也一模一样。
- **中央大喇叭的噪音** — 只跟着发现的 "死法" 数量走，绝不跟着人头走。刚才这把 847 只特种兵的混战，最后也就总结出了 12 条死法，而不是叽叽喳喳的 847 条。

**当你的狼群规模飙过 1000 时，你得留意这几个坑：**

- **WAL 写入踩踏。** SQLite 的 WAL 模式在应付 50 只疯狗同时死命写时游刃有余，但如果你敢把写入并发拉过 200 到 300 的红线，它就会开始互殴。系统出厂预设的那个 50 的 `max_concurrent` 是我故意卡死的保守线；如果你真的想同时放出几万匹狼，你最好把那个数据库按块切碎 (shards)，或者直接换用什么天马行空的分布式后端。
- **同步的大喇叭广播。** 在这把局里，把一条死法同时塞给 23 只嗷嗷待哺的特种兵也就是一眨眼的事。但如果你手上有 5,000 号人，你最好把这种广播切成异步的 (async)，免得大喇叭卡死了整个大军的冲锋节奏。
- **热缓存 (Hot-cache) 吃内存。** 每只活着的特种兵大概需要死死咬住 2MB 左右的 VFS 热状态内存：50 只并发大概吃你 100MB，500 只的话就能飙到 1GB。备好你的内存条。
- **空降前的热身时间。** 放出那 847 匹狼花了 17 秒；如果是 5,000 匹，估计得热身 100 秒左右。有点烦，但不至于死人。

上面这一整套大戏，全是在一台 MacBook Pro 上闭着眼睛跑完的。当你真正想搞上千只并发特种兵时，你可能真的需要买点像样的铁疙瘩服务器，甚至可能得挂个分布式事件库 —— 不过放心，切入点早就留好了：VFS、事件流水账和 blob 存储这三大护法，全都被包在了干净利落的接口后面，你想换成什么变态的分布式系统随便你，甚至外面的特种兵根本都不会察觉。

---

我不介意再把开头的话念一遍：847 只 agent，8 分 47 秒内完工，809 份文件强力升天，31 份文件在翻车后自我净化，7 份文件认怂交接，0 事故侵入主干 —— 顺便还砍掉了 245 万个没必要烧的代币。这所有的丰功伟绩和血海深仇，全都被压缩进了这个 214MB 的 SQLite 文件里。它就在那里，你可以拷贝，可以拷问，直到宇宙尽头。

## 顺藤摸瓜

- [README 首页](../README.md) — 纵览全局，所有的文档都从这开始
- [破局战法 (Use Cases)](../use-cases.md) — 这里有更多从尸山血海里趟出来的实战打法
- [核心部件指南：CORAL 蜂巢网络](../meta-harness.md#coral-getting-unstuck-v020)
- [破局战法：多特种兵共生演化 (CORAL)](../use-cases.md#multi-agent-co-evolution-coral)
- [深层架构：我们是怎么搞定扩容与隔离的](../architecture.md)

---

*bene 基于 MIT 协议开源，并且是一个极端的 "数据不出境" 偏执狂：刚才这把漫天撒网、这些特种兵的一举一动、以及这堆铁证如山的流水账，全都被死死焊在了你本地这台破电脑的 SQLite 文件里。只要你不去配置外网端点，哪怕是一个标点符号也飞不出去。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
