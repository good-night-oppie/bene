# 在 0.3 秒内，把一场搞砸的数据库迁移连根拔起

跑高危迁移操作，手边得备着一颗后悔药：当一场涉及 200 万行的补数据 (backfill) 操作在半截腰尿了裤子时，只需一条指令，0.31 秒内抹平一切灾难，而且隔壁的其他 agent 连个喷嚏都不会打。

> **在雷区前拍个快照，意味着一场 200 万行的翻车事故，能被压缩成 0.31 秒的起死回生。**

*第一阶段完工后拍个快照；第二阶段的补数据在跑到第 847,412 行时，因为异常的 NULL 值自己踩了急刹；耗时 0.3 秒完成回滚；其他跑数据分析的 agent 丝毫不受影响。*

## 先看疗效：一键时光倒流

在 agent 自己踩下急刹车之前，这波补数据操作已经往 `subscription_tier` 里灌了 64,412 个要命的 NULL 空值。抢救的手段非常朴实无华，就是对着之前贴好标签的快照敲一条命令：

```text
bene restore migration-agent --label pre-backfill

# 正在把 migration-agent 摁回快照点: pre-backfill
#
# 抹平了以下改动:
# --- migration/state.json
# -  "phase": "backfill",
# -  "rows_processed": 847412,
# -  "null_count": 64412,
# -  "status": "anomaly_paused"
# +  "phase": "schema_complete",
# +  "rows_processed": 0,
# +  "status": "ready_for_backfill"
#
# 抢救完毕，耗时 0.31 秒
```

0.31 秒。这只 agent 的虚拟文件系统 (VFS) —— 也就是每个 bene agent 赖以生存的私有结界 —— 就这么干脆利落地回到了那个已知的安全节点；刚才第二阶段灌进去的所有脏水，仿佛从未存在过。接下来的内容，我们将带你复盘这条一键指令背后到底发生了什么。

## 发车前的战术板

任务：给一张坐拥 200 万行数据的 `users` 表加个新列 `subscription_tier` —— 这列将决定每个用户能看啥不能看啥。计划分三步走，每走完一步打个快照，在最容易翻车的那步埋好异常探测雷达：

```python
# migration/add_subscription_tier.py

PHASES = [
    {
        "name": "schema_change",
        "sql": "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20)",
        "checkpoint": "pre-backfill"
    },
    {
        "name": "backfill",
        "sql": """
            UPDATE users
            SET subscription_tier = s.tier
            FROM subscriptions s
            WHERE users.id = s.user_id
        """,
        "batch_size": 10_000,
        "anomaly_check": True,
        "checkpoint": "pre-constraint"
    },
    {
        "name": "enforce_constraint",
        "sql": "ALTER TABLE users ALTER COLUMN subscription_tier SET NOT NULL",
        "checkpoint": "complete"
    }
]
```

与此同时，有两只负责数据分析的 agent (`analytics-agent-1` 和 `analytics-agent-2`) 正在这张表里疯狂跑查询。但因为它们各自被关在不同的 VFS 里，从物理结构上就注定了它们绝对不可能被这边的乌烟瘴气波及。

## 动数据前，先买保险

第一阶段是便宜且随时能反悔的 —— 一个根本不会动任何表数据的 `ALTER TABLE`。跑完它，然后给这个时空节点钉上一个标签：

```text
bene run migration-agent "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20)"

# [migration-agent] 表结构修改: 成功
# [migration-agent] 即将进入第二阶段，共有 2,041,847 行数据等待更新

bene checkpoint migration-agent --label pre-backfill

# 快照已生成: pre-backfill
# 第一阶段战况: 表结构已刷入，尚未动任何数据
# 时间戳: 2026-04-13T01:33:11Z
```

这个标签就是你的全套保险。执行这番骚操作的是 `migration-agent`；接下来无论补数据阶段惹出多大的祸，只要一句 `bene restore migration-agent --label pre-backfill`，这只 agent 就会被生生拽回这个节点：表结构刚配好，一行数据都没碰，随时可以再来一把。

## 补数据阶段：自己把自己给掐了

第二阶段开始按每批 10,000 行的吞吐量狂灌数据，同时异常雷达每隔 5 万行就会嗅探一下 NULL 值的比例。前面一路绿灯，直到冲到第 847,412 行：

```text
[backfill]  已处理 100,000 行  NULL 数量: 0      (0.0%)  ✓
[backfill]  已处理 200,000 行  NULL 数量: 0      (0.0%)  ✓
[backfill]  已处理 300,000 行  NULL 数量: 0      (0.0%)  ✓
[backfill]  已处理 500,000 行  NULL 数量: 0      (0.0%)  ✓
[backfill]  已处理 700,000 行  NULL 数量: 0      (0.0%)  ✓
[backfill]  已处理 847,412 行  NULL 数量: 64,412 (7.6%)  ✗

警报：探明异常状况：NULL 率 7.6%，已击穿 0.0% 的安全红线
预期: subscription_tier 列里应该有 0 个 NULL
实测: 在处理完的 847,412 行里，足足有 64,412 个 NULL

已强制熔断迁移操作。停止后续数据灌入。
```

没有哪个倒霉的 DBA 盯着屏幕。这只 agent 纯靠自己踩死了刹车 —— 因为 7.6% 的 NULL 比例，绝对不可能活着熬过第三阶段那个死盯 NOT NULL 约束的鬼门关。

## 验尸报告早就写好了

在踩死刹车前，这只 agent 顺手在自己的 VFS 里留下了一份验尸报告。调出来看一眼，只需一条命令：

```text
bene read migration-agent /logs/anomaly.md

## 异常报告: subscription_tier 爆出 7.6% 的 NULL 值

发现第一个 NULL 值: user_id 8,042,183 (出自 205 批中的第 84 批)
死状特征: 所有爆 NULL 的用户，注册时间全在 2021-03-15 之前

死因追溯: 那些在 `subscriptions` 表建表之前就注册的远古老用户，
在 `subscriptions` 表里压根就没有他们的名字。
所以 JOIN 一把梭的时候，直接给这帮老兵塞了 NULL。

补救方案: 拿 COALESCE 糊一层，给找不到对应关系的用户强行塞个 'free':
  UPDATE users
  SET subscription_tier = COALESCE(s.tier, 'free')
  FROM subscriptions s
  WHERE users.id = s.user_id

预估被波及的行数: 大概 156,000 名远古老兵 (注册早于 2021-03-15)
```

所有的 NULL 全都来自 2021-03-15 之前建号的用户 —— 这个时间点比 `subscriptions` 这张表出生的日子都早，JOIN 当然连个鬼都匹配不到。补救的方法，无非就是垫一层 `COALESCE`。

## 洗心革面，重头再来

一键倒流 (就开头那条命令)，拍上 `COALESCE` 的兜底补丁，重新发车。还是原来的配方，还是原来的批次大小，结局截然不同：

```text
[backfill]  500,000 行   NULL 数量: 0  (0.0%)  ✓
[backfill]  1,000,000 行 NULL 数量: 0  (0.0%)  ✓
[backfill]  1,500,000 行 NULL 数量: 0  (0.0%)  ✓
[backfill]  2,000,000 行 NULL 数量: 0  (0.0%)  ✓
[backfill]  2,041,847 行 NULL 数量: 0  (0.0%)  ✓ 补全完毕

[phase 3]  ALTER TABLE users ALTER COLUMN subscription_tier SET NOT NULL
[phase 3]  大功告成 — 2,041,847 行数据已被 NOT NULL 约束死死锁住

迁移落锤。总耗时: 47 分钟 (算上了中途的翻车回滚和重新爬起来的时间)。
```

墙上的时钟走了 47 分钟，翻车、抢救、通关，一把梭。

## 亲眼查查这场爆炸的波及范围

隔离不能只停留在画大饼上，它是经得起你亲手扒开查验的。就在刚刚回滚落锤的那一瞬间，整个狼群的战况如下：

```text
bene ls

# NAME                STATUS    UPTIME   EVENTS
# migration-agent     restored  14m      847 (刚被抢救过)
# analytics-agent-1   running   14m      1,204
# analytics-agent-2   running   14m      983
# dashboard-agent     running   14m      441
```

三个毫不相干的 agent，连一毫秒都没被打断过。每一只都在自己被 SQLite 锁死的结界里干活，所以那场弄到一半被强行掐断的脏数据迁移，对它们来说连个影子都没出现过 —— 而在回滚落锤之后，那些脏数据在这世上更是连灰都扬了。

## 把整场战役再倒放一遍

拉出完整的流水账，你就能看到这条一镜到底的生死线 —— 空投、拍照、爆雷、抢救、打补丁、绿灯通关：

```text
时间      动作        所属战区            行数       NULL数   战况批注
--------  ----------  ------------------  ---------  ------  --------------------------------
01:33:08  spawn       —                   —          —       特种兵空投，系统唤醒
01:33:11  checkpoint  pre-schema          0          0       贴标: pre-schema
01:33:14  schema      schema_change       0          0       ALTER TABLE: 顺利落刀
01:33:16  checkpoint  pre-backfill        0          0       贴标: pre-backfill
01:33:18  backfill    backfill            847,412    64,412  爆雷: NULL 飙到了 7.6%
01:34:01  restore     —                   0          0       强行摁回 pre-backfill (0.31s)
01:34:04  fix         —                   —          —       掏出 COALESCE 缝针
01:34:06  backfill    backfill            2,041,847  0       全量补齐: 0 NULL，全绿
02:21:14  constraint  enforce_constraint  2,041,847  0       NOT NULL 镣铐锁死
02:21:17  checkpoint  complete            2,041,847  0       全剧终，迁移落锤
```

如果半道上没有那个卡脖子的探针，你接到第一波警报的时间绝对是第二天早上用户的口水淹没客诉的时候，那时脏数据早都漏到大盘上了。而现在，这堆脏东西连 agent 的沙盒都没能爬出来，并且抹平这场灾难，只花了 0.3 秒。

## 顺藤摸瓜

- [核心部件指南：时空快照 (Checkpoints)](../checkpoints.md)
- [破局战法：数据库回滚续命](../use-cases.md#db-migration-rollback)
- [破局战法 (Use Cases)](../use-cases.md) — 更多这种极限拉扯的骚操作
- [架构设计：VFS 引擎底层扒皮](../architecture.md)
- [README 首页](../README.md) — 全景大局观和全套文档入口

---

*bene 基于 MIT 协议开源，并且是个极端的 Local-first 原教旨主义者：你在这页上看到的每一条指令，全都在单机上跑完，绝对没有任何一滴数据被偷偷运输出去。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
