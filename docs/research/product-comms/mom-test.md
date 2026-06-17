# The Mom Test — Rob Fitzpatrick

> **用途**: BENE landing zh rewrite v2 evidence base (post user-rejection 2026-06-13).
> **Lenny bucket**: "I want to increase my product success rate"
> **Slug**: `mom-test` · **KAOS key**: `research/product-comms/mom-test`
> **Distilled by**: workflow `wf_3585b934-c3c`, parallel subagent with structured schema + web-cited sources.

## Thesis

Fitzpatrick 的核心论断不是「多聊客户」，而是大多数客户对话都在生产 bad data——三类垃圾：compliments（夸奖）、fluff（"我通常 / 我一定会 / 我可能"这类泛化、假设、未来时）、ideas（功能 wishlist）。compliments 是 fool's gold——发亮、扎眼、毫无价值；fluff 里最致命的一句是 "I would definitely buy that"。垃圾的来源是：你一旦把 idea 摆上桌，客户立刻从 source of truth 退化成想帮你的 consultant，开始描述 hypothetical 而不是 reality。Fitzpatrick 的三条规矩反过来：(1) Talk about their life instead of your idea；(2) Ask about specifics in the past instead of generics or opinions about the future；(3) Talk less and listen more。判定一次对话是否成立的标准不是对方点头，而是 commitment——time、reputation、money 三种 currency 里的至少一种被掏出来。"I love it" 不是信号；约下一次 30 分钟、把你介绍给老板、把钱预付出来——才是。这本书的母题贯穿写产品和写文案：**你在找真相，不是在等掌声**——you're searching for the truth, not trying to be right。这条原则映射到 landing copy：别描述你的方案有多妙，描述读者已经活过的那个具体场景。

## Reader brain moves

作者引导读者思路的具体动作。每条带概念名 + 怎么做 + 书里的具体例子。

### 1. 先把读者放回他自己已经活过的具体一刻 (anchor to a past scene before any pitch)

**怎么做**: Fitzpatrick 反复要求把对话从 'what would you do' 拽回 'talk me through the last time that happened'。不是问 '你觉得这功能怎么样'，而是问 '上一次这事发生是什么时候？你那天做了什么？花了多少钱？还试过别的什么？'——他让读者重新走一遍 workflow，而不是想象未来。

**书里的具体例子**: 书里推荐的两个标准开场是 'Talk me through your workflow' 和 'Talk me through the last time that happened'——这两句把对话从 hypothetical 钉死在 last-time-it-happened 的具体场景上。

### 2. 把抽象主张换成可付出代价的 commitment (replace opinions with currency)

**怎么做**: Fitzpatrick 主张一切对话以 commitment 收尾：time、reputation、money 三种 currency 之一。'compliment costs nothing, so it's worth nothing'——免费的信号没数据量。对应到 landing：别让读者只是点头，让他做一个具体动作（跑一条命令、看一个 diff），那个动作本身就是 currency。

**书里的具体例子**: 书里反复强调 meeting 成功的标准不是 '愉快'，而是 '对方掏出 time / reputation / money 之一'。一个零成本的 verbal 'I love it' 在他眼里就是 zombie lead——看上去活着，其实不会转化。

### 3. 诊断 bad data 三连：compliment / fluff / idea (name the failure mode before fixing it)

**怎么做**: Fitzpatrick 不是说 '客户在骗你'，他诊断出三种具体的 bad data：compliments（夸奖）、fluff（generics / hypotheticals / future tense）、ideas（功能 wishlist）。每一种都有专门的反制：deflect compliments、anchor fluff、dig beneath ideas。这种 '先命名失败模式，再开处方' 的结构让读者立刻能在自己对话里识别问题。

**书里的具体例子**: 书里给出 'the world's most deadly fluff is: I would definitely buy that'——一句话钉死最容易让人上当的 fluff 模式（feels concrete，但全是未来时）。

### 4. 把'听起来严谨'的提问当陷阱来拆 (the trap of false rigor)

**怎么做**: Fitzpatrick 警告：'Would you pay X for a product which did Y?' 不比 'Do you think it's a good idea?' 更可信——加了数字反而更危险，因为它 feels rigorous and truthy。对应到文案：精确的技术参数（'0.3 秒跑完'、'37 个工具'）听起来严谨，但如果没钉到读者具体的一刻，就和 'would you pay X' 一样是 false rigor。

**书里的具体例子**: 书里把 'Would you pay X for Y?' 列为 bad question 的标准案例，并明确说：加数字不是改善，是用 truthy 的外观掩盖 hypothetical 的本质。

### 5. 搜索真相而不是等掌声 (search for truth, not gold star)

**怎么做**: Fitzpatrick 反复说：'You're searching for the truth, not trying to be right' 和 'It's not anyone else's responsibility to show us the truth. It's our responsibility to find it'。文案对应：别写 '我们做了 X，是不是很厉害'，写 '在你笔记本上，这一条声明可以这样验'——把举证责任揽到自己身上，让读者去 falsify。

**书里的具体例子**: Fitzpatrick 把客户对话比作 archaeological site：真相在底下，但很脆，blunt instrument（leading question / pitch）一下去就碎了。

## Copyable patterns — 可被 agent 抄走的 5 个句式

每个 pattern 都附带把当前 BENE landing 一条具体 offender 句子改写过的样例。

### Pattern 1: Last-time-it-happened anchor (用上一次发生的具体一刻替换抽象定义)

**句式模板**: [读者上一次踩到这个坑的具体场景：动词 + 对象 + 后果] → [当时他下意识做了什么] → [那一招为什么没救回来] → [BENE 在这一刻具体做什么动作]

**应用到 BENE landing**:

> 原句『一个 agent = 一份 SQLite 文件。cp 备份它，sqlite3 直接读它，不需要任何 API key，不上云。』 → 改写：『上一次 agent 把 main 分支改炸的时候，你 git stash 了，发现 stash 救不回未写入磁盘的中间状态。这一刻你想要的不是一个新概念，是 cp bene.db backup.db——文件就在那儿。』

### Pattern 2: Deflect-compliment, surface the verb (把"X是Y"换成"读者能对它做的具体动词")

**句式模板**: 去掉所有 'is/equals/就是' 句式，把名词等价换成读者可以执行的动词链：[读者动词1] + [读者动词2] + [读者动词3]，每个动词后面跟它具体作用在什么对象上

**应用到 BENE landing**:

> 原句『把 Context Engineering 落到一份 SQLite 文件里。』 → 改写：『你可以 grep 上一次 agent 错在哪、diff 它改了什么、cp 一份留作下次回放——同一个文件，三件事。』

### Pattern 3: Anchor the fluff (把"通常/每一步/任何"等泛化词钉到一个具体回合)

**句式模板**: 把 '每一次 / 任何 / 所有' 这类 quantifier 删掉，替换成 '上一次 X 发生时' 的具体一回合 + 那一回合里读者具体看到了什么

**应用到 BENE landing**:

> 原句『每个 agent 一份隔离 VFS，每一步进 checkpoint，每条声明都能本地重跑。』 → 改写：『你让 Claude Code 改了 replicas: 3 → 0，prod 挂了。下一秒 bene diff 让你看见它具体动了哪一行，bene restore 把它退回去——不是 git ritual 是一条命令。』

### Pattern 4: Currency-of-commitment close (用读者能付出的最小代价收尾，而不是 verbal 点头)

**句式模板**: [一条具体命令 / 一个具体动作] + [它本地 / 离线 / 一分钟内跑完] + [它产出的可检验的对象：diff / hash / 数值裁决]

**应用到 BENE landing**:

> 原句『这页上的每条声明，在你笔记本上一分钟内就能验。』 → 改写：『bene demo --no-ui，0.3 秒，离线跑完。跑完之后你手里多三样东西：一份 probe 的 ACCEPT/REJECT 裁决、触发它的具体数值、能 sha256 复核的 spec hash。点头不算数，这三样算。』

### Pattern 5: Name the bad-data failure mode before the fix (先命名读者上一次踩的具体陷阱，再说 BENE 怎么修)

**句式模板**: [读者下意识用的工具：git stash / git revert / 重新 prompt] → [它在这种具体场景下为什么救不回来] → [BENE 在同一个场景下读者改打哪条命令]

**应用到 BENE landing**:

> 原句『智能体把生产搞挂了。一条命令滚回去。』 → 改写：『agent 把 replicas 改成 0，git stash 救不回——因为出错的不只是 working tree，还有 agent 中途写进 .env / 临时文件的副作用。这一刻你打 bene restore <checkpoint>，文件、scratchpad、它中途学到的 lesson，一起退到那个点。』

## Anti-patterns — 作者明确反对的 3 个模式

每个 anti-pattern 引一句当前 BENE landing 的 verbatim 文案做对照，并给出改写。

### Anti-pattern 1: X = Y reductive equation (用等号把产品压成一个名词)

**作者为什么反对**: Fitzpatrick 的第一条规矩就是 'Talk about their life instead of your idea'——一旦你把 idea 摆出来，客户就从 source of truth 退化成 consultant，开始描述 hypothetical。'一个 agent = 一份 SQLite 文件' 是最纯粹的 idea-first 句式：它定义了一个等价关系，但读者上一次踩坑那一刻并没有在思考 '我需要一份 SQLite 文件'，他在思考 'git stash 怎么没救回来'。这种等式句让读者立刻进入 hypothetical 模式，正是 The Mom Test 全书要拦截的对话失败。

**BENE landing 现在的违规句 (verbatim)**:

> 一个 agent = 一份 SQLite 文件。`cp` 备份它，`sqlite3` 直接读它，不需要任何 API key，不上云。

**用这本书的纪律改写**:

> 上一次 agent 把 main 分支改炸、git stash 救不回来的时候，你想要的不是一个新概念。你想要的是：cp bene.db backup.db（文件就在那儿）、sqlite3 bene.db 查它改了哪几行（不用启服务）、不联网（你那台笔记本本来就在飞机上）。

### Anti-pattern 2: Compliment-shaped value prop (用泛化夸奖代替具体动作)

**作者为什么反对**: Fitzpatrick 把 compliments 列为三大 bad data 之首，称之为 'fool's gold of customer learning: shiny, distracting, and entirely worthless'。'落到一份 SQLite 文件里' 是典型的 self-compliment——它在夸自己干净、收敛、优雅，但没有告诉读者他能用这份文件干什么具体的事。读者上一次踩坑的那一刻不需要被告知架构有多优雅，需要被告知下一条命令打什么。

**BENE landing 现在的违规句 (verbatim)**:

> 把 Context Engineering 落到一份 SQLite 文件里。

**用这本书的纪律改写**:

> scratchpad、lessons-learned、跨 session 记忆——之前这三样各自塞在 prompt、临时文件、文档里。现在你可以 grep 一遍，找出 agent 上次错在哪；diff 一下，看下一个 agent 读到了什么；cp 一份，留给下周回放。同一个文件，三件事。

### Anti-pattern 3: Generic quantifier fluff (用'每一步/任何/每一条'等泛化词代替具体一回合)

**作者为什么反对**: Fitzpatrick 明确把 'always / usually / never / would' 列为 fluff——generic 和 hypothetical 的语言会让读者切换到泛泛而谈，而不是回到上一次具体的事件。'每个 agent 一份隔离 VFS，每一步进 checkpoint，每条声明都能本地重跑' 三个 'every' 连发，正是他书里点名的 fluff 句式：它听起来 comprehensive，但读者无法把任何一句钉到自己上一次的具体一回合上。

**BENE landing 现在的违规句 (verbatim)**:

> 每个 agent 一份隔离 VFS，每一步进 checkpoint，每条声明都能本地重跑。

**用这本书的纪律改写**:

> 上一次你让 Claude Code 改 replicas，它把 3 改成了 0，prod 挂了。这一刻你打 bene diff，看见它动了哪一行；bene restore <checkpoint>，文件、scratchpad、agent 中途写下的 lesson 一起退回去；bene probe replay，0.3 秒重跑那一条声明，吐出触发它的具体数值。

## Sources cited

- **[goodreads]** https://www.goodreads.com/quotes/10670144 — Verbatim three rules: 'Talk about their life instead of your idea. Ask about specifics in the past instead of generics or opinions about the future. Talk less and listen more.'
- **[blog_summary]** https://mtlynch.io/book-reports/the-mom-test/ — Backs the three categories of bad data (compliments / fluff / ideas) and the 'compliments are the fool's gold of customer learning' framing.
- **[blog_summary]** https://medium.com/binsights/the-mom-test-by-rob-fitzpatrick-book-summary-d3e4ffd8b128 — Backs the 'most deadly fluff is I would definitely buy that' and the bad-question rewrites ('Would you pay X for Y' as false rigor).
- **[blog_summary]** https://dev.to/egepakten/the-mom-test-chapter-5-commitment-and-advancement-1k27 — Backs the commitment-and-advancement framework: three currencies (time, reputation, money) and 'a meeting succeeds when it ends with commitment to advance'.
- **[blog_summary]** https://www.koji.so/blog/mom-test-customer-interviews-2026 — Backs the 'searching for the truth, not trying to be right' quote and 'It's not anyone else's responsibility to show us the truth' principle.
- **[blog_summary]** https://www.ricklindquist.com/notes/the-mom-test-by-rob-fitzpatrick — Backs the deflect-compliments / anchor-fluff / dig-beneath-ideas remediation framework.
- **[blog_summary]** https://www.thoughtleadersintech.io/the-mom-test/ — Backs the bad-question vs good-question rewrites ('Do you think it's a good idea?' fails; 'Talk me through the last time that happened' succeeds).
- **[book_text]** The Mom Test, Rob Fitzpatrick, Chapter 1 (three rules) and Chapter 2 (avoiding bad data) — Original source for all framework concepts; verified via multiple independent summaries above rather than quoted from memory.

---

*Distilled with no hallucinated quotes — every specific claim is either backed by a cited URL or described abstractly. If you find a quote that's wrong, check sources_cited first; the workflow ran with explicit "do not invent" instructions.*
