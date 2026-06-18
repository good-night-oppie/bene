# 在 0.3 秒内拔掉 Agent 捅出的娄子，而且你的代码库连皮都不会破

这篇教程会教你如何放纵一只 agent 去做高危修复：亲眼看着它把事情搞砸，然后只把这只惹祸的 agent 一键回滚到作案前的清白之身 —— 而你本地的 git checkout，以及其他正在跑的 agent，连一根毛都不会掉。

> **动手前先拍快照，意味着就算天塌下来，你付出的代价也只是一行回滚指令，而不是浪费掉你一整个早上的光阴。**

你即将走完的实盘演练长这样：先遇到一个飘红的测试；接着一个看似合理的修复硬生生把 1 个红的搞成了 4 个；启动单 agent 局部回滚；让 agent 给自己写一份翻车验尸报告；最后掏出对的解法，一口气把整个套件打成 47 个绿灯。这里的每一条流水，全部来自于一次真实的抓轨：

*一镜到底的排障流水：放狗，拍快照，引发连环翻车 (从 1 挂到 4)，时光倒流，出具验尸报告，掏出正确补丁，47 绿通关。*

## 陷阱：一个飘红的用例，和一场即将到来的雪崩

一个支付服务刚经历了一场重构，把 `amount` 字段从 `float` 统改成了 `str`，说是为了保证 API 序列化的统一。结果 CI 跑出来，只挂了一个：

```text
FAILED tests/test_payment.py::test_payment_decimal_precision
AssertionError: 10.00 != 10.0

Expected: Decimal('10.00')
Got:      10.0

1 failed, 46 passed in 3.2s
```

精度 Bug 简直就是在勾引你去做类型强转，而类型强转，恰恰是所有雪崩的起点：`float`、`Decimal` 还有 `str`，它们各自在判等、舍入以及 JSON 化上，都有自己的一套脾气。在这里随手敲一行看似人畜无害的补丁，很容易就会把一个红灯超级加倍成四个 —— 最后让你满头大汗地去修你自己糊的屎，而不是修原来的 Bug。

## 扎营：把这颗雷丢进沙盒里

放出去一只负责 QA (质量保障) 的 agent。这小子会领到一份整个支付服务的全量拷贝，而这份拷贝，死死地关在只属于它的、由 SQLite 撑腰的虚拟文件系统 (VFS) 里 —— 这是一个绝对物理隔离的黑盒，里面的爆炸绝对波及不到你本地的磁盘，也绝对伤不到它的兄弟 agent。

```text
bene spawn payment-qa --from ./payment-service

# [payment-qa] agent 成功投放到战场  vfs_id=pqa-8f3a
# [payment-qa] 开始跑 pytest...

FAILED tests/test_payment.py::test_payment_decimal_precision
  AssertionError: assert Decimal('10.00') == 10.0

  payment/models.py line 47:
    return float(self.amount)  # ← 这就是重构后留下的那行屎

1 failed, 46 passed
```

现在，这颗飘红的雷被完完全全关进了 `payment-qa` 的 VFS 结界里。你硬盘上的东西，连个字节都没动。

## 买保险：拍快照，只拍 agent 的，不拍 repo 的

这小子登场后的第一个动作，不是动刀子，而是拍照。一个快照 (checkpoint)，就是在特定时间点上，把这只 agent 整个 VFS 里的身家性命全盘冻结。注意，这个结界只罩着 `payment-qa`，别人无权干涉。

```text
bene checkpoint payment-qa --label pre-fix-attempt

# 快照已生成: pre-fix-attempt
# 冻结了多少个文件: 23
# VFS 里的战况: 1 个红灯, 46 个绿灯
# 时间戳: 2026-04-11T02:14:33Z
```

23 个文件，外加那份确凿的战损底稿 (1 挂 46 过)，全部备案。如果等下这小子乱动手脚把事情搞砸了，所谓的 "抢救" 无非就是把这单只 agent 强行摁回到这个节点 —— 没有任何全局的 repo 重置，也不会有任何一颗流弹伤到其他正在半空飞行的 agent。

## 看着它作死：从 1 挂变成 4 挂

这小子的第一次尝试，跟大多数人类工程师的本能反应一模一样。断言里要的是 `Decimal('10.00')`；这字段不知道吐了个什么玩意出来；那就粗暴地套个 `float()` 强转，齐活。

```python
# payment/models.py — agent 的第一刀
def get_amount(self):
-   return self.amount
+   return float(self.amount)  # 暴力洗成 float
```

在处理钱的时候，这种强转会直接粉碎掉单元测试死死守住的底线：`float(Decimal('10.00'))` 会被直接阉割成 `10.0`，小数点后两位的精度当场灰飞烟灭。原本只红 1 个的局，现在红了 4 个：

```text
FAILED tests/test_payment.py::test_payment_decimal_precision
FAILED tests/test_payment.py::test_payment_total_rounding
FAILED tests/test_payment.py::test_invoice_line_items_sum
FAILED tests/test_payment.py::test_refund_partial_amount

4 failed, 43 passed in 3.4s
```

雪崩开始了。如果你是在平时的 git 分支上干活，到这一步，大多数人已经开始在这堆烂摊子上往死里垒第二层屎了。

## 抢救：一条指令，让它时光倒流

```text
bene restore payment-qa --label pre-fix-attempt

# 正在把 payment-qa 摁回快照点: pre-fix-attempt
# 时光倒流影响了 1 个文件: payment/models.py
# @@ -44,7 +44,7 @@
#  def get_amount(self):
# -    return float(self.amount)
# +    return self.amount
#
# 抢救完毕，耗时 0.04 秒
# VFS 战况核实: 1 个红灯, 46 个绿灯 (已确认恢复到了作死前的清白之身)
```

整场回滚只花了 0.04 秒，并且用实打实的战报验明了正身：回到了 1 挂 46 过，跟拍照时分毫不差。就在这套骚操作上演的同时，隔壁那些跑集成测试的、写文档的、扫安全的 agent 兄弟们，全都在各自的轨道上岁月静好 —— 物理隔离的魔法是施加在 VFS 上的，而不是宿主机器的硬盘上。哪怕你同时拉起了 4 只 agent，其中一只哪怕自爆了又复活，其他 3 只连眼皮都不用眨一下。

## 哪里是 git 够不着的地方，哪里就是审计日志的主场

| 你靠手敲 git 能干嘛 | 你靠 bene 快照能干嘛 |
|---|---|
| `git reset --hard` 直接把整个代码库祖坟给刨了 | `bene restore` 只会让那只惹祸 agent 的 VFS 时光倒流 |
| `git log` 只能死板地记下人类敲过的 commit | 审计流水 (journal) 会把每一次对文件的下刀，连带前后跑出来的测试战报，像烙印一样死死咬在一起 |
| `git stash` 必须等你这个碳基生物想起来去敲 | 所有的 agent 在动刀子前都会像膝跳反射一样自动拍快照 |
| `git bisect` 需要你苦逼地二分查找那个万恶之源 | 一条 SQL，就能扒出这小子在 02:14:41 到底拉了哪泡屎，硬生生搞出了 3 个新红灯 |

## 验尸：让 agent 自己给自己写检讨

就在刚才那波智障操作翻车的时候，这只 agent 已经在它的 VFS 里老老实实写下了一份结构化的验尸报告。因为时光倒流这波操作只抹除了 `payment/models.py` 里的作案痕迹，所以这份报告被完好无损地保留了下来：

```text
bene read payment-qa /qa/failure_report.md

## 翻车复盘报告: test_payment_decimal_precision

案发源头：在做算钱这档子事时，精度丢了。

`amount` 字段本该用 `Decimal` 来保证绝对的算术精度。重构完以后，
`models.py` 直接裸吐了这个字段的值，而它现在变成了一串字符 ("10.00")。
但单元测试那边，死死盯着要一个 Decimal('10.00')。

字符串 != Decimal。所以判等的时候直接被崩了。

找死的操作：暴力转成 `float`，直接把尾数精度给扬了。
float("10.00") == 10.0 — 小数点后两位当场失踪，更别提 float
在海量运算下根本就不满足结合律。

阳关大道：用 Decimal(str(amount)).quantize(Decimal('0.01'))
这么写既保住了精度，又生吃了字符串输入，还完美符合 IEEE 854 里关于
金融算术那套比命还重的十进制规范。
```

证据确凿，签字画押：报告里点名了哪条路是绝路，点明了哪条路能活，并且只要数据库不删，这笔账随时能用 SQL 查出来。

## 拔毒：祭出真解

顺着那份检讨书里给的阳关大道，重新落刀：

```python
# payment/models.py — 正确的解法
from decimal import Decimal, ROUND_HALF_UP

def get_amount(self) -> Decimal:
    """吐出一个带 2 位精度死守的 Decimal。"""
    return Decimal(str(self.amount)).quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP
    )
```

```text
tests/test_payment.py::test_payment_decimal_precision  PASSED
tests/test_payment.py::test_payment_total_rounding     PASSED
tests/test_payment.py::test_invoice_line_items_sum     PASSED
tests/test_payment.py::test_refund_partial_amount      PASSED
... (剩下的 42 个也是绿的)

47 passed in 3.1s
```

满门 47 口，全绿通关。连带刚才那波雪崩时被顺手活埋的 4 个，也一并活过来了。

## 秋后算账：用 SQL 重播全场

上面这一出戏里的每一个动作，早就被死死钉在了 bene 的 SQLite 流水账里：

```text
时间点       动作        作案地点                 案底备注
---------  ----------  ---------------------  --------------------------------
02:14:29   spawn       —                      agent 空投，VFS 结界生成
02:14:31   tool_call   —                      跑了把 pytest: 1 挂, 46 过
02:14:33   checkpoint  —                      贴标: pre-fix-attempt
02:14:41   write       payment/models.py      第一次作案: 暴力套 float()
02:14:43   tool_call   —                      又跑 pytest: 4 挂 — 雪崩了
02:14:44   write       /qa/failure_report.md  验尸报告已出具，找出了死因
02:14:45   restore     —                      时光倒流，强行摁回到 pre-fix-attempt
02:14:52   write       payment/models.py      祭出 Decimal.quantize() 真解
02:14:54   tool_call   —                      最后一把 pytest: 47 绿全通
```

从 02:14:29 的空投进场，到 02:14:54 的全绿通关，下过的每一刀、每一次倒带、每一次拉起 pytest，全都被打上了时间戳，且全都能被 SQL 拷问。Git 历史只能告诉你哪几行代码变了；但这条流水账能扒出到底是哪一次红灯，逼着它写出了哪一坨屎。就算这套系统是在大半夜自己跑的，第二天你端着咖啡吃早饭的时候，照样能拿着这张表复盘全场 —— 细到连是哪一刀砍出了雪崩，又是哪一发指令把雪崩给吞了，都能看得清清楚楚。

## 顺藤摸瓜

- [核心部件指南：时空快照 (Checkpoints)](../checkpoints.md) — 扒光快照和回滚的底层骨架
- [审计流水表：events (事件表)](../schema.md#events) — 拿 SQL 去拷问你自己的流水账
- [破局战法：全自动端到端自愈流水线 (Self-Healing CI)](../use-cases.md#end-to-end-self-healing-ci-worked-example) — 这套绝活在战术板上的原档
- [破局战法 (Use Cases)](../use-cases.md) — 更多起死回生和运筹帷幄的套路
- [README 首页](../README.md) — 全套文档大地图

---

*bene 基于 MIT 协议开源，并且只在你的本地吃算力；没有任何一滴数据会被偷偷运走。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
