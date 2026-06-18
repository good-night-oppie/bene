# 换模型如换刀：切模型不断骨的防退化兵法

*MLOps 篇*

给系统换底层大模型，就该像升级个普通第三方库一样简单：改一行代码，剩下的生杀大权交给测试套件。这篇教程教你怎么在 CI/CD 流水线里焊死一道基于 BENE 的防退化闸门 (regression guard)：它会把你的整个基准测试套件 (benchmark suite) 在候选模型上完整重播一遍，只要发现新模型在你最在乎的核心指标上敢拉胯，直接当场毙掉这次发布。

> **一道 CI 关卡，耗时 12 分钟：五个核心靶场在新模型上重头跑一遍，只要有任何一项得分的跌幅超过 5%，闸门就会自动锁死，发布当场被拦下。**

*一次端到端的实盘升级演示：套件重播，`code_review` 这个靶场的成绩暴跌 8.4%，闸门死死卡住了发布，紧接着靠跑了一波 5 轮的演化搜索把分数捞了回来，最后这个升级包在周一早上安稳上线。*

接下来，我们将带你完整跟踪一次真实的切模型实盘 —— 从 `claude-sonnet-4-5` 升级到 `claude-sonnet-4-6` —— 从开局的一路绿灯，到中途发布被拦下，再到重振旗鼓恢复基线。整个过程全自动运转，无需任何活人盯盘。

## 焊在流水线上的一道关卡

这道防退化闸门，在 CI 里只不过是一步任务。拉起一只配置了候选新模型的 agent，拿老模型当年留下的满分快照作为对标基准 (anchor)，重播全套靶场，最后用一条 SQL 查询把那些跌幅惨不忍睹的成绩抓出来：

```yaml
# .github/workflows/model-regression.yml
- name: 跑防退化重播套件
  run: |
    bene spawn regression-check-v46 \
      --model claude-sonnet-4-6 \
      --baseline-checkpoint baseline-v45

    bene run regression-check-v46 \
      "run_benchmarks text_classify code_review sentiment math_qa tool_calling"

    bene --json query "
      SELECT benchmark, delta_pct
      FROM regression_results
      WHERE run_id = 'regression-check-v46'
        AND delta_pct < -5.0" \
    | jq -e '. | length == 0' \
    || (echo "探明退化倒车行为 — 已锁定发布闸门" && exit 1)
```

三条指令，死守一个契约。`bene spawn` 捏出了一只咬死 `baseline-v45` (老版本基准快照) 作为对标参照物的 agent；`bene run` 把这五大靶场从头到尾重刷一遍；最后那发 `--json query` 查询，冷酷地把所有跌幅超过 -5.0% 的靶场全揪出来。只要查出来的结果不是空的，`jq -e` 就会报错，整个 CI 步骤直接以 exit 1 收场，谁也别想发版。

这些跑出来的所有家当 —— 分数、快照、执行踪迹 —— 全部安安稳稳地躺在一个本地的 `bene.db` SQLite 文件里。你想备份就 cp，想查就 diff，想打包就压缩。没有任何一滴数据会流向云端。

## 一览众山小：完整的攻防闭环

每次换模型，这六步雷打不动：

1. **切模型 (Swap)** — 在配置文件里把枪管换成候选的新模型。
2. **重播 (Replay)** — 跑完整个靶场套件，把出炉的分数和老模型的基线快照挨个对齐比拼。
3. **把门 (Gate)** — 只要有任何一项跌幅跌穿了底线，放手让 CI 把构建流水线给崩了。
4. **抢修 (Repair)** — 把那个翻车的靶场单独拎出来，挂上元脚手架 (meta-harness)，拿之前沉淀的火种跑几轮定向短促突击。
5. **立新规 (Re-baseline)** — 把抢修成功的新 prompt 和新模型一起拍个快照，作为明天的新基准。
6. **放行 (Ship)** — 只要闸门见绿，随时可以发版上线。

本教程接下来的部分，将带你身临其境地走完这六步。

## 真刀真枪的换防与判卷

流水线开转 12 分钟后，每一个靶场都拿到了自己的宣判书：

```text
Benchmark      v4-5  v4-6  Delta   Status
-------------  ----  ----  ------  -------------------
text_classify  0.87  0.87   0.0%   毫无波澜 (NO CHANGE)
tool_calling   0.88  0.91  +3.4%   高歌猛进 (IMPROVED)
math_qa        0.74  0.76  +2.7%   高歌猛进 (IMPROVED)
sentiment      0.83  0.81  -2.4%   轻微退化 (REGRESSION)
code_review    0.83  0.76  -8.4%   致命倒车 (CRITICAL REGRESSION)  ← 拦下来了
```

先看最右边那一列。有三个靶场稳住了甚至涨分了 —— `tool_calling` 涨了 3.4%，`math_qa` 涨了 2.7%，`text_classify` 稳如老狗。有两个栽了。`sentiment` 掉了 2.4%，还在这个团队能捏着鼻子认了的容忍度以内。但 `code_review` 暴跌了 8.4% —— 直接击穿了警戒线，而且这偏偏是用户最容易体感到的核心功能。如果单看总体大盘的平均分，新模型是赢了的；但如果真把它发到生产环境，它绝对会迎来一场客诉的血洗，因为用户在使用时摸到的从来不是什么 "大盘平均分"。

闸门冷酷地吐出了一行 JSON 宣判书：

```json
[{"benchmark": "code_review",
  "baseline_score": 0.83,
  "new_score": 0.76,
  "delta_pct": -8.4}]

# 揪出 1 处致命倒车
# CI 闸门: 拦截 (FAILED)
# 发布状态: 锁定 (BLOCKED)
```

查出了脏东西，返回了非零错误码，发版被死死摁住 —— 还顺带发了条警报，指名道姓地点出了到底是谁在拖后腿。那个 -5.0 的警戒线，你可以针对每个靶场自己捏：在那种出了错要赔钱的地方收紧一点，在那种日常就喜欢随风摇摆的任务上放宽一点。最牛逼的地方在于，没人需要把这条红线记在脑子里；不管今天有没有活人盯着看板，这道闸门该劈下来的时候，绝对不会手软。

## 拿 Diff 拷问死因

拦下发布只能算赢了一半。另一半是搞清楚到底哪里不对劲了。`bene diff` 把两场考试的卷子按在一起比对，直接出具了一份死因诊断书：

```text
bene diff baseline-v45 regression-check-v46 /results/code_review_failures.md

## code_review 坠机复盘: 0.83 → 0.76 (-8.4%)

### 翻车死状
新模型在区分 BLOCKER (致命) 和 IMPORTANT (重要) 时，眼神极其迷离。

v4-5: 错判 BLOCKER/IMPORTANT 的概率: 14%
v4-6: 错判 BLOCKER/IMPORTANT 的概率: 31%

### 翻车现场还原 (新模型的作案录像)
输入: "SQL query is vulnerable to injection — must fix before merge" (带注入漏洞——合并前必须修掉)
标准答案: BLOCKER
它的回答: IMPORTANT (新模型自行把严重度给降级了)

### 死因追溯
你现在用的这套 prompt (脚手架) 是专门给 v4-5 那种服从指令的脑回路线路量身定制的。
v4-5 对 "must fix" 这类关键词有着膝跳反射般的敏感度 → 看到就判 BLOCKER。
v4-6 则喜欢对严重度进行一番更加细致入微的 "深度思考" → 结果思虑过度，降级成了 IMPORTANT。

这锅不该新模型背 —— 纯粹是现有的脚手架跟新模型的脑回路八字不合。
之前搜索战役里攒下来的那个 `two_step_attr_merged (两步属性提取)` 策略，
或许更能对上 v4-6 的脑电波。
```

错判率翻了一倍都不止，从 14% 狂飙到 31% —— 而新模型本身并没有变蠢。问题出在老脚手架是在疯狂白嫖 v4-5 的一个怪癖：一看到 "must fix" 这类字眼，v4-5 就会无脑判死刑 (BLOCKER)；而 v4-6 却试图去推演背后的严重逻辑，而不是单纯的关键词匹配。同样的 RLHF 训练配方，养出了截然不同的条件反射。所以这病的解法不是把模型滚回去 —— 而是要为这个你真正想用的新模型，重新摸出一套能让它舒服的 prompt 脚手架。

## 把丢掉的分亲手拿回来

诊断书里已经指明了一条明路，所以抢修行动根本不用从零开始抓瞎。直接拿老基线里的巅峰战果当火种，在这一个拉胯的靶场上，给新模型跑个 5 轮的小型定向爆破：

```bash
bene mh search \
  -b code_review \
  --model claude-sonnet-4-6 \
  -n 5 \
  --seed-from baseline-v45

# [mh-search] 正在从 baseline-v45 抽取火种...
# [mh-search] 提取火种: two_step_attr_merged  acc=0.76 (在 v4-6 上只跑出了 0.76, 尽管它当年在 v4-5 上是 0.83)
# [mh-search] 从已知的巅峰阵地起飞，不再摸黑
```

```text
[iter 1/5]  two_step_attr_merged_v46  acc=0.78  +0.02  进化成功 (IMPROVED)
[iter 2/5]  attr_merged_explicit      acc=0.81  +0.03  进化成功 (IMPROVED)
[iter 3/5]  attr_merged_explicit_v2   acc=0.81  —      原地踏步
[iter 4/5]  blocker_severity_v46      acc=0.83  +0.02  进化成功 (IMPROVED)  ← 成功收复失地
[iter 5/5]  blocker_severity_merged   acc=0.83  —      榨干了，没进步

最终王者: blocker_severity_v46  acc=0.83  (阵地已全面收复)
```

在第 4 轮时，`blocker_severity_v46` 成功登顶，拿到了 0.83 分 —— 完美在全新的模型上，复刻了那个巅峰分数。那套 "两步走" 的解题思路经受住了模型更迭的考验；它缺的，仅仅是针对 v4-6 的脾气，明明白白地写上一套判定严重度的细则而已。修复的补丁本身小得可怜：无非就是在 system prompt 里多加了一小节话。

## 填平那个隐秘的夺命深坑

在升级大模型时，最致命的幻觉莫过于这句咒语："新模型更牛逼，所以我们的产品躺着就能变得更好。" 多数时候确实如此。但这句话绝对经不起推敲 —— 一个模型在宏观的智力大盘上高歌猛进的同时，极有可能在一夜之间丧失掉某种你的脚手架极其依赖的、古早的神经质行为，因为你现在的这套 prompt，完全就是照着老模型的那些怪癖长出来的。如果没有这道闸门，这种背刺式的能力退化，最终都会变成周末夺命连环 Call，或者凌晨 3 点的传呼机报警。而有了这道闸门，它最多只会变成流水线上一个刺眼的红色 CI 报错。

如果你把这道防线撤了，重演这波发版：周五下午高高兴兴上线；到了周六，客诉工单雪片般飞来，全在骂你们的系统在背地里偷偷乱降漏洞严重度；周日的一整天，值班工程师都在满头大汗地抓虫，最后才绝望地发现，这特么压根就不是代码 bug，而是 prompt 水土不服。加上了这道防线，同样的升级包会被死死拦下，被迫回炉拿上一套专为 v4-6 调教过的、且实盘验证过的全新脚手架，然后在周一早上毫发无伤地顺利发车上线。

这，就是一道防退化闸门存在的全部意义。

## 顺藤摸瓜

- [README 首页](../README.md) — 纵览全局，以及找到所有文档的老家
- [破局战法 (Use Cases)](../use-cases.md) — 更多从真实生产环境的尸山血海里爬出来的战术
- [核心部件指南：演化脚手架 (Meta-Harness)](../meta-harness.md) — 扒光搜索循环的底层逻辑
- [破局战法：模型防退化闸门 (Model Regression Guard)](../use-cases.md#model-regression-guard) — 这套打法的浓缩速记版
- [教程：t01 — Meta-Harness 从 48% 到 83% 的奇迹](t01-bene-meta-harness.md) — 看看那个用来当火种的 `baseline-v45` 巅峰成绩是怎么打出来的

---

*bene 基于 MIT 协议开源。你在本教程里看到的这套腥风血雨的攻防演练，全都在你本地完成 —— 没有任何一滴数据会流出你的机器。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
