# Checkpoints — 专给 Agent 吃的后悔药

在让 agent 去碰那些高风险脏活之前，先给它打个 checkpoint。万一搞砸了，只需敲一行 restore 命令就能满血复活，再也不用含泪从头开始重建状态。bene 支持随时将 agent 的全部脑容量和文件资产无损冻结；你可以把时间线拨回任意一个坐标，或者直接拿两个坐标进行贴身比对。

> **一行代码存档，一行代码读档，一行代码对比 —— 跨越时空的整条履历，全攥在你电脑里的那唯一一个 SQLite 文件里。**

---

## 冻结一个已知稳妥的状态

```python
cp = db.checkpoint(agent_id, label="before-migration")
```

```bash
bene checkpoint <agent-id> --label "before-migration"
```

每拍下一次快照，就会死死钉住以下内容：

- VFS 里的每一份文件，全按内容寻址打成了 blob 引用 —— 绝对不存半点冗余字节。
- 通过 `db.set_state(...)` 写入大脑的每一把 KV 钥匙。
- 冻结时刻的精确时间戳，以及你随手贴上去的任何 metadata。

这种快照机制记的是 blob 指针而不是文件拷贝，所以大胆放开手脚去存，权当免费。

### 自动化快照机制

`ClaudeCodeRunner` 自带求生本能，每熬过 `checkpoint_interval` 指定的轮次 (默认是 10)，就会自动打点存档:

```yaml
# bene.yaml
ccr:
  checkpoint_interval: 10
```

---

## 逆转一场灾难级的失控

随时随地倒转时间轴，回到过去的某个定格点：

```python
db.restore(agent_id, checkpoint_id)
```

```bash
bene restore <agent-id> --checkpoint <checkpoint-id>
```

恢复操作底层走的是纯净的 SQL —— bene 会直接暴力重写这个 agent 名下的文件记录行和状态行 —— 因此不管时空畸变有多严重，落地都只在毫秒之间，且绝不会波及其他任何 agent，数据也永远锁死在你的物理机里。

你应该养成的肌肉记忆是：打好快照，放手去搏，见势不妙，立马回滚。

```python
cp = db.checkpoint(agent_id, label="pre-migration")
try:
    result = await ccr.run_agent(agent_id, "Migrate schema to v3")
except Exception:
    db.restore(agent_id, cp)
    raise
```

---

## 扒开细节看看究竟动了哪

把两个时空坐标拿来当面对质：

```python
diff = db.diff_checkpoints(agent_id, checkpoint_id_a, checkpoint_id_b)
```

```bash
bene diff <agent-id> --from <checkpoint-id-A> --to <checkpoint-id-B>
```

每一份比对战报都会赤裸裸地交代：

- **无中生有 (Files added)** — 那些只在快照 B 里冒出来的路径。
- **毁尸灭迹 (Files removed)** — 曾经活在 A 里，但在 B 里灰飞烟灭的。
- **改头换面 (Files modified)** — 路径没变，但是两边捏着的 SHA-256 指纹对不上号的。
- **篡改记忆 (State changed)** — KV 脑容量里那些新增的、丢掉的、或是被塞了新值的键。
- **暗度陈仓 (Tool calls between)** — 夹在这两个时空快照之间偷偷调用的 tool。

一份典型的出战报告长这样 —— 顶上是一个由路径和状态把守的表格 (不显示文件体积)，紧跟着是被扒光的 state 变更以及 tool-call 账单：

```text
            文件战损报告 (File Changes)
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Status     ┃ Path               ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ ADDED      │ /tests/test_auth.py│
│ MODIFIED   │ /src/auth.py       │
│ REMOVED    │ /src/auth_legacy.py│
└────────────┴────────────────────┘

           记忆篡改记录 (State Changes)
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Status     ┃ Key      ┃ Value                        ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ MODIFIED   │ progress │ 75 -> 100                    │
│ MODIFIED   │ status   │ "in-progress" -> "complete"  │
└────────────┴──────────┴──────────────────────────────┘

      快照夹缝里的工具调用 (Tool Calls Between Checkpoints)
┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ Tool      ┃ Status  ┃ Duration ┃ Tokens ┃
┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ read_file │ success │ 15ms     │ 120    │
└───────────┴─────────┴──────────┴────────┘
```

如果哪个环节岁月静好毫无动静，终端会直接甩你一句 `No state changes` (记忆未曾变动) 或是 `No tool calls between checkpoints` (夹缝中并无调用)。

如果你加上了 `--json` 标志，这堆东西就会乖乖被打进一份机器友好的包裹里：`{"files": {"added": [...], "removed": [...], "modified": [...]}, "state": {"added": {...}, "removed": {...}, "modified": {...}}, "tool_calls": [...]}`。

### 让两种方案互殴

给两种解题思路各打一张快照，然后把它们拉回现实来打擂台：

```python
cp_a = db.checkpoint(agent_id, label="approach-A")
# ... 放出方案 A 的恶犬 ...
cp_b = db.checkpoint(agent_id, label="approach-B")

# 对薄公堂
diff = db.diff_checkpoints(agent_id, cp_a, cp_b)
```

---

## 翻找时空存根

把一个 agent 兜里揣着的所有快照票根全抖搂出来：

```python
cps = db.list_checkpoints(agent_id)
# [{"checkpoint_id": "01K...", "label": "before-migration", "created_at": "..."}]
```

```bash
bene checkpoints <agent-id>
bene --json checkpoints <agent-id>
```

### 给快照钉上墓志铭

label 只是个简短的名号；但 metadata 可以塞进长篇大论的注解 —— 比如测试战报、触发它的罪魁祸首、或者是留给后人的遗言：

```python
cp = db.checkpoint(agent_id, label="v2-attempt")

# Bene 的 facade 外壳只吃一个短平快的 label。想要塞入硬核的 metadata，你需要直接绕开它去找底层 manager 办事：
# db.checkpoints.create(agent_id, label="v2-attempt", metadata={
#     "notes": "全盘切换到了 JWT — 干掉了基于 session 的老掉牙认证",
#     "test_results": {"passed": 14, "failed": 0},
#     "triggered_by": "CI 流水线第 428 号战役",
# })
```

这堆私货会在 `bene checkpoints <agent-id>` 以及 Dashboard 的 Checkpoints 标签页里昭告天下。

---

## 这堆快照究竟吃掉我多少硬盘？

几乎就是个零头。真正重头的文件血肉全部只在 blob 库里躺着唯一一份 (有 SHA-256 钥匙锁着，外加 zstd 压缩伺候)；区区一个 checkpoint 不过就是一撮干瘪的指针。两份相似度高达 95% 的快照，并排站在一起占用的空间几乎等同于一份。

想要无情火化掉那些再也没有快照认领的孤魂野鬼 blobs？

```python
db.blobs.gc()  # 毫不留情地铲除所有 ref_count 归 0 的 blob
```

---

## 连锅端走换台机器接着跑

将一个 agent 导出会连带着把它名下所有的快照一起塞进一个极度便携的文件里：

```bash
# 连锅端出整个 agent 的祖宗十八代 (当然包含了它所有的 checkpoints)
bene export <agent-id> -o agent-snapshot.db

# 换台机器，当场复活
bene import agent-snapshot.db
```
