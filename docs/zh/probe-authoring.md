# 手写一刀致命的探针 (Authoring a probe)

**探针 (probe)** 就是一道提前注册好、拿哈希锁死、绝不准半路篡改的击杀闸门 (kill gate)。它里面定义了一个指标 (metric)、一个比较符 (comparison) 和一根红线 (threshold)；当受审对象越过红线时，它就 **放行 (passes)**，一旦跌破红线，它就会毫不留情地 **就地击杀 (kills)**。

探针跑完后，只会吐出三种判决：

- **晋升 (ACCEPT)** — 毫发无损；受审对象扛住了每一道闸门。
- **枪毙 (REJECT)** — 至少死在了一道闸门上；说明代码越改越烂 (regressed)。
- **废弃 (VOID)** — 探针本身是个永远不会翻车的假测试 (inadmissible)，或者它要测的那个指标根本就没取到；这次测试不作数，绝对不能当成过关。

我们搞这套极其变态的刑具，唯一的目的就是去逮住那些 "明明绿了但代码依然是死的" 的假测试。这篇指南会教你到底该怎么写出真正能杀人的探针，外加两个能把它直接焊死在 CI 流水线上的 CLI 指令。

## 铁律：连输都输不掉的测试，根本不配叫测试

当你调用 `register()` 注册一个探针时，BENE 会极其冷血地执行一次 **可采纳性自证 (admissibility self-test)**：它会让基线数据 (baseline) 自己和自己打一架 (也就是进步为零的情况)。如果连这都触发不了探针的击杀，说明这个探针是个不管喂什么屎都会判绿的废物 —— BENE 会当场给它打上 `inadmissible` (不可采纳) 的耻辱印记，以后哪怕你强行跑它，它也只会吐出 **VOID**，这辈子都不可能给你发 ACCEPT。

这颗解药，专门用来对付那种极其经典、但每次都能把系统坑死的代码：

```python
assert isinstance(session_id_propagated, bool)   # 不管是 True 还是 False 它都是绿的
```

上面这句废话只是在检查数据的**长相 (shape)**，它压根不管事情到底办成了没。如果环境坏了，那个值悄无声息地变成了 `False`，这句测试依然绿得发亮。如果把它写成探针，因为基线数据本身长得就像个布尔值，所以它连基线都杀不死 —— 系统会当场判定它为 `inadmissible`，把这颗糖衣炮弹直接没收。

## 能把带病代码一刀砍死的，才是好刀

一个真正合格的探针，必须是一把 **能把已知的烂代码一刀砍死** 的快刀。常见的造刀方法就两种：

1. **跟健康的基线对切 (相对值)。** 给闸门打上 `relative_to_baseline: true` 的烙印，然后去比 `(当前得分 − 基线得分)` 是不是越过了一个正数的容忍度。这时候如果是原封不动地拿基线来测，进步分是零，探针就会当场击杀 → 证明这刀能杀人，可采纳。
   ```python
   {"name": "quality_improves", "metric": "quality", "op": ">=",
    "threshold": 0.05, "relative_to_baseline": True}   # 基线 = 一次健康的满分跑酷
   ```
2. **拿带病的基线当靶子 (绝对值)。** 直接设一条绝对的红线，而那条红线是 **带病** 的基线绝对跨不过去的。
   ```python
   {"name": "propagated", "metric": "propagated_true", "op": ">=",
    "threshold": 1.0}                                   # 基线 = 那个链路全断、分数为 0 的垃圾环境
   ```

### 不可采纳 → 直接废除的踩雷区

最容易踩进去的坑，就是拿 **健康** 的基线去定一条绝对红线：

```python
# 极其脑残的写法 — 会被打上 inadmissible，然后每次都给你悄无声息地返回 VOID
{"name": "no_regression", "metric": "errors", "op": "<=",
 "threshold": 0, "relative_to_baseline": False}        # 一个健康的基线 errors 已经是 0 了 → 直接过关 → 永远杀不了人
```

因为基线 (0 个错) 本来就满足 `errors <= 0`，所以这个闸门在自证环节连一滴血都放不出来 → 判定为不可采纳 → VOID。想填这个坑，要么老老实实去拿健康的基线比相对值 (`errors` 绝不能 *变多*)，要么去拿那个真带着 bug 的基线来设绝对红线。

## 注册探针 (只能用 Python)

因为探针那个评估函数 (`evaluate_fn`) 的工作是把一坨极其复杂的受审对象嚼碎，吐出一个形如 `{metric: number}` 的字典，这玩意根本没法序列化进终端命令行里，所以注册这事只能在 Python 里办：

```python
from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe

b = Bene("bene.db"); ensure_v2(b.conn)
store = EngramStore(b.conn, b.blobs)

GATE = {"name": "quality_improves", "metric": "quality", "op": ">=",
        "threshold": 0.05, "relative_to_baseline": True}
Probe("quality-probe", [GATE], dict).register(store, b.conn, baseline={"quality": 0.0})
b.close()
```

调用 `register()` 的瞬间，系统会把这个闸门规格洗干净、用 sha256 上一把死锁、当场拉出去跑可采纳性自证、然后把这套规格和耻辱印记一起死死拍进数据库。以后谁要是敢偷偷改规格，运行时直接赏你一个 `LockTamperError` (篡改锁死异常) —— 想改题偷偷重考？门都没有。

## 把探针焊进 CI：`bene probe run --json`

`bene probe run` 会把那套锁死的规格拖出来、验完哈希锁、拿 JSON 文件喂进指标里过堂、把判决结果写进案底，并且 **只要结果是 REJECT 或 VOID 就直接抛出非零退出码 (non-zero exit)**，让流水线瞬间红灯：

```bash
echo '{"quality": 1.0}' > subject.json
echo '{"quality": 0.0}' > baseline.json

# 受审对象进步了 1.0 (>= 0.05 的红线) -> 准许晋升 (ACCEPT)，退出码 0
bene --json probe run quality-probe --subject subject.json --baseline baseline.json
```
```json
{
  "status": "ACCEPT",
  "probe": "quality-probe",
  "gate_results": [
    {"name": "quality_improves", "value": 1.0, "passed": true, "killed": false}
  ],
  "reason": "",
  "engram_id": "01K...",
  "killed_gates": []
}
```

要是受审对象敢没越过红线，直接 REJECT，退出码不是零：

```bash
echo '{"quality": 0.0}' > flat.json
bene --json probe run quality-probe --subject flat.json --baseline baseline.json || echo "build failed (exit $?)"
```
```json
{
  "status": "REJECT",
  "probe": "quality-probe",
  "gate_results": [
    {"name": "quality_improves", "value": 0.0, "passed": false, "killed": true}
  ],
  "reason": "",
  "engram_id": "01K...",
  "killed_gates": ["quality_improves"]
}
```

把 `bene probe run … --json` 直接塞进 CI 的一个步骤里就行：`REJECT → 退出码炸了 → 编译失败`。

## 绝杀那些杀不死人的假探针：`bene probe ls --check-admissible`

如果有个探针侥幸躲过了作者的眼睛，它会被默默打上 `inadmissible` 的烙印，然后每次跑都默默吐 VOID —— 虽然没搞出假绿灯，但这种沉默极其致命。把它揪出来在 CI 里游街：

```bash
# 只要库里藏着任何一个不可采纳的探针，直接抛出非零退出码炸机
bene --json probe ls --check-admissible
```
```json
{
  "ok": false,
  "inadmissible": ["vacuous-probe"],
  "total": 3
}
```

所有探针都合格时返回 0，只要查出一个杀不死人的假探针，不但非零退出，还会把罪魁祸首的名字吐出来。把它跟你的测试步骤跑在一起，绝不允许任何一句空话在这里骗过关。

## 案发现场复盘：灯塔链路探针 (the lighthouse trace probe)

去看 [`examples/lighthouse_trace_probe.py`](../examples/lighthouse_trace_probe.py)，里面完完整整地重现了 `isinstance(..., bool)` 坑死全场的那一幕。那个看长相的闸门会被当场剥夺考试资格打成 VOID，而那个一刀见血的 `propagated_true >= 1` 闸门，则极其精准地把坏环境一枪崩了，然后给修好的环境发了张绿卡：

```bash
uv run python examples/lighthouse_trace_probe.py
```
```
[shape gate ] registration: inadmissible
[shape gate ] run verdict : VOID  (bene refuses a gate that cannot fail)
[falsifiable] registration: admissible
[falsifiable] broken env  : REJECT  (killed: ['session_id_propagated'])
[falsifiable] fixed env   : ACCEPT

PASS-31 reproduced: shape gate VOID, broken REJECT, fixed ACCEPT ✓
```

## 顺藤摸瓜

- [`examples/lighthouse_trace_probe.py`](../examples/lighthouse_trace_probe.py) — 那个能直接跑起来的铁证。
- [CLI 指令大黄页 (cli-reference.md)](cli-reference.md) — 这里有这几个指令的所有变态参数。
- [接入 BENE (integrating-bene.md)](integrating-bene.md) — 去看看评测闸门在系统的那五个生命周期里到底卡在哪一层。
- [深层架构 (architecture.md)](architecture.md) — 去扒一扒那个上过哈希锁的击杀闸门，以及底下的印记底座到底长啥样。
