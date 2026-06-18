# 12 秒内，揪出到底是谁动了奶酪

不离开 SQLite 半步，搞定凌晨两点的生产环境连环大爆炸：对着 `bene.db` 拍两发 SELECT 语句，直接顺藤摸瓜，从 23% 的 HTTP 500 报错率一路追杀到引起这一切的那一行配置；再补第三发查询，把灾后复盘 (post-mortem) 的干货数据直接给你吐出来。

> **正因为每一只 agent 留下的每一次笔迹，都被死死钉在了一条只能追加 (append-only) 的流水账上，所以 "到底改了啥？" 变成了一个用 SQL 就能解决的问题 —— 而不是一场长达 90 分钟的午夜悬案。**

*实盘抓轨记录：凌晨 02:17 传呼机炸响，02:17:12 敲下第一条查询，02:17:24 拿获真凶，紧接着拍上热补丁，看着报错率从 23% 归零。*

## 凌晨两点的午夜凶铃

现在是凌晨 2 点，线上 23% 的 HTTP 请求正在疯狂爆 500 报错。不管你接下来要怎么抢救，你满脑子其实只有一个疑问：到底特么谁动了什么？

如果没有这套流水账，找出这个答案纯靠人肉拼图 —— 去业务日志里 grep 捞针，去散落各处的发布系统里对时间线，去翻近期的 git commit，去叫醒最后一个发版的倒霉蛋。做好熬 45 到 90 分钟的心理准备。但在 BENE 里，任何 agent 在这颗星球上写过的任何一个字节，早就变成了同一个库里带着时间戳的一行记录；下面这整场破案过程，只需要两条查询，也就是两发 `SELECT ... WHERE timestamp > ...` 的事。

## 从发病症状开始顺藤摸瓜

直接拷问流水账：都在爆什么错，是哪只 agent 报出来的，从什么时候开始的：

```sql
SELECT timestamp, agent_id, tool_name, error
FROM tool_calls
WHERE status = 'error'
  AND timestamp > datetime('now', '-1 hour')
ORDER BY timestamp DESC
LIMIT 20
```

```text
经过时间               agent_id      tool_name      error
T+48m05s              api-gateway   db_query       ConnectionPoolError: 连接池已被榨干 (pool exhausted)
T+48m04s              api-gateway   db_query       ConnectionPoolError: pool exhausted
T+48m02s              api-gateway   db_query       ConnectionPoolError: pool exhausted
... (底下的 844 行全长这样，全是 ConnectionPoolError，全来自 api-gateway)

第一起命案发生在: T+48s  (也就是传呼机炸响前的 47 分钟)
```

案情一目了然：847 条 `ConnectionPoolError`，全部出自 `api-gateway`，第一例命案正好发生在 47 分钟前。症状很明显 —— 连接池被榨干了。而这个时间点就是最致命的线索：在 47 分钟前，一定有人干了什么。

## 追杀作案现场

还是同一个库，换张表。每一次对 VFS 的写入，都会连同时间戳、作案 agent、文件路径和一段罪证快照被死死记下 —— 那么我们就问问它，在这起命案爆发前的那 2 个小时里，到底往硬盘里写了些啥：

```sql
SELECT timestamp, agent_id, file_path, content_preview
FROM vfs_events
WHERE timestamp > datetime('now', '-2 hours')
  AND event_type = 'write'
ORDER BY timestamp ASC
```

```text
经过时间               agent_id      file_path           content_preview
T+0                   api-gateway   config/db.yaml      ...pool_size: 2...
T+1s                  api-gateway   config/app.yaml     ...log_level: debug...
T+48s                 api-gateway   logs/error.log      ConnectionPoolError...
```

逮住了：`config/db.yaml`。这笔写入卡在第一起命案爆发前不到一分钟的时间点上，而且罪证快照里赫然写着 `pool_size: 2`。

## 拿 Diff 甩它脸上

BENE 里的二进制大对象 (Blob) 全是基于内容寻址的，所以要比对发版前的快照和现在的命案现场，其实就是一次哈希对比外加两次 Blob 提取 —— 也就是一次精准的 diff：

```diff
--- config/db.yaml (发版前的快照)
+++ config/db.yaml (命案现场 HEAD)
@@ -8,7 +8,7 @@
 database:
   host: postgres-primary.internal
   port: 5432
-  pool_size: 10
+  pool_size: 2
   pool_timeout: 30
   max_overflow: 5
```

就动了一行：`pool_size` 被人从 `10` 硬生生砍成了 `2`。这刀下在 01:28:53；第一起报错紧跟在 01:29:41 爆发 —— 生产环境洪流般的流量，只花了 48 秒就把一个容量只有 2 的连接池吸了个精光。

**传呼机 02:17:00 炸响。02:17:24 拿获真凶。从被叫醒到查明死因：仅仅 12 秒。**

## 带着证据，滚滚向前 (Fix forward)

在动任何东西之前，先给这个案发现场拍个快照锁死 —— 等天亮了写复盘报告时绝对用得上 —— 然后再把修正的配置糊上去：

```text
bene checkpoint api-gateway --label broken-pool-size-2
# (尸骨已保存，留作复盘)

# 拍上热补丁
bene write api-gateway /config/db.yaml \
  "$(cat config/db.yaml | sed 's/pool_size: 2/pool_size: 10/')"
```

然后，睁大眼睛看着它一分钟一分钟地爬出地狱：

```text
时间     报错量
02:17    847
02:18    412
02:19     89
02:20     14
02:21      2
02:22      0  ✓
```

热补丁拍下去，5 分钟内，从 23% 的血崩巅峰，一路清零。

## 复盘报告自己就写好了

灾损数据，直接从你刚才起手的那个 `tool_calls` 表里捞：

```sql
SELECT
  COUNT(*)                                              AS affected_requests,
  MIN(timestamp)                                        AS outage_start,
  MAX(timestamp)                                        AS outage_end,
  ROUND(
    (JULIANDAY(MAX(timestamp)) - JULIANDAY(MIN(timestamp))) * 24 * 60, 1
  )                                                     AS duration_min
FROM tool_calls
WHERE status = 'error'
  AND agent_id = 'api-gateway'
  AND error LIKE '%ConnectionPoolError%'
```

```text
受灾请求量(affected_requests) 命案开始(outage_start) 命案结束(outage_end) 持续时长分钟(duration_min)
4,847                         T+48s                  T+53m10s             52.4
```

历时 52.4 分钟，4,847 次请求被击穿，而这一切的源头，仅仅是 01:28:53 落下的那行配置。扣动扳机的那一刻、第一起阵亡、随后的每一次哀嚎、直到最后抢救成功的时刻，全被死死封印在同一个 SQLite 文件里 —— 不需要你跨系统去生搬硬套时间轴，也不需要你凭借残存的记忆去拼凑现场。

## 为什么传统做法要熬 90 分钟

把两种姿势摆在一起看：

```text
传统人肉排查流                     BENE
---------------------------------  -----------------------------------------
grep 抠业务日志 (10 分钟)          对着流水账表跑一发 SQL 查询 (<1 秒)
翻发版系统查记录 (5 分钟)          包含在上面那发查询里了
肉眼啃 git commits (5 分钟)        每一笔 VFS 写入本身自带时间戳
摇人，拉会 (20 分钟)               大可不必
跨系统拼凑时间线 (15 分钟)         一句 ORDER BY timestamp ASC 搞定
```

流水账具备的三个先天优势，直接把这 90 分钟给抹平了：

1. **默认开启的日记本。** `api-gateway` 摸到 `config/db.yaml` 的那一瞬间，事件表里就已经自动夯进了一行带着时间戳、作案 agent ID 和罪证快照的记录 —— 不需要你提前记得去写打点代码。
2. **纯 SQLite 驱动的底层。** 一个带时间过滤的 SELECT 毫秒级就能跑完，中间没有那些劳什子的聚合服务，没有臃肿的 Elasticsearch 集群，也没有什么狗屁数据清洗管道。
3. **内容寻址的大对象存储。** 拿 `pre-deploy (发版前)` 对比 `HEAD`，在底层仅仅是比一下哈希然后捞内容而已 —— 不到一秒就能极其精准地给你糊一脸单行 diff。

这上面的每一个环节，都用不着你去 grep、去发版系统里挖坟、或者是把睡梦中的队友拖起来。当 agent 敲下的每一个字符从它诞生的第一天起，就被关在一个全盘可 SQL 查探的追加式日志里时，每一次排障开场时的那个终极疑问，永远都有一个确凿的答案在原地等你。

## 顺藤摸瓜

- [README 首页](../README.md) — BENE 全景大局观和全套文档入口
- [破局战法 (Use Cases)](../use-cases.md) — 更多来自泥坑一线的实战套路
- [数据解剖图：events 事件表](../schema.md#events) — 刚才这几条 SQL 查的到底是啥表
- [破局战法：凌晨两点的急诊排障](../use-cases.md#2am-incident-response) — 浓缩版的急救手册
- [命令行兵器谱：bene query / bene search 指令](../cli-reference.md)

---

*BENE 基于 MIT 协议开源，并且是一个极端的 Local-first 原教旨主义者：你在这页上看到的每一条 SQL 拷问，全都只在你硬盘上的那个 SQLite 文件里完成，绝对没有任何一滴数据流出过你的机器。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
