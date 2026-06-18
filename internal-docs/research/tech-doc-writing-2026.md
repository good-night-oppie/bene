# Tech-doc writing 2026 — distilled evidence base

> **Use**: source-of-truth for the BENE doc rewrite (post user-rejection 2026-06-14).
> **Generated**: workflow `wf_612d1867-d29` (4 parallel research subagents, web-cited).
> **Compose with**: skills/stop-slop (EN prose discipline) + skills/stop-slop-zh (中文 discipline).

This file consolidates four research dimensions:

1. Canonical English tech-doc writing — structure (Diátaxis), voice (Google + Microsoft + Stripe), sentence/paragraph rhythm (Microsoft + Write the Docs), and code-block discipline (Stripe + Google) — applied to the BENE 41-doc corpus (tutorials t00-t11, reference cli/mcp/schema, how-tos checkpoints/memory/skills, explanation architecture/philosophy/BENE2-DESIGN).
2. canonical Chinese tech-doc writing — structural model, tone discipline (中文工程师 voice), 段落/句长 conventions, 中英文混排排版, 翻译腔 / AI-味 anti-patterns
3. structural-clarity-for-technical-prose
4. Human-vs-AI-slop voice in modern dev tool docs (2023-2026): sentence-level signals, structural patterns of exemplary docs, AI-slop tells, applied to BENE

---

## Canonical English tech-doc writing — structure (Diátaxis), voice (Google + Microsoft + Stripe), sentence/paragraph rhythm (Microsoft + Write the Docs), and code-block discipline (Stripe + Google) — applied to the BENE 41-doc corpus (tutorials t00-t11, reference cli/mcp/schema, how-tos checkpoints/memory/skills, explanation architecture/philosophy/BENE2-DESIGN).

### Sources consulted

- **Diátaxis Framework (Daniele Procida)** — https://diataxis.fr/ ; https://diataxis.fr/tutorials/ ; https://diataxis.fr/reference/
  - The de-facto IA model adopted by Django, Cloudflare, Gatsby, NumPy, Kubernetes — author maintains the canonical site; quoted verbatim above.
- **Google Developer Documentation Style Guide** — https://developers.google.com/style/highlights
  - Public style guide governing all developers.google.com content; explicit, prescriptive, used as baseline by thousands of OSS projects.
- **Microsoft Writing Style Guide — Top 10 tips** — https://learn.microsoft.com/en-us/style-guide/top-10-tips-style-voice
  - Governs every learn.microsoft.com page; concrete before/after rewrites quoted verbatim; updated 2025-04.
- **Write the Docs — Documentation Principles** — https://www.writethedocs.org/guide/writing/docs-principles/
  - Community-maintained principles (ARID, Skimmable, Exemplary, Consistent, Current) cited across the tech-writing field.
- **Stripe Docs (style + Markdoc engineering blog + third-party teardowns)** — https://docs.stripe.com/ ; https://stripe.dev/blog/markdoc ; https://www.moesif.com/blog/best-practices/api-product-management/the-stripe-developer-experience-and-docs-teardown/ ; https://apidog.com/blog/stripe-docs/
  - Industry benchmark for dev docs (three-column layout, runnable code, prose-code linking) — corroborated by Mintlify, Moesif, Apidog teardowns and Stripe's own engineering blog.
- **Docs for Developers (Bhatti, Corleissen, Lambourne, Nunez, Waterhouse — Apress 2021, ISBN 978-1-4842-7216-9)** — https://www.apress.com/gp/book/9781484272169
  - Authored by the docs leads at Alphabet/Google Cloud, GitHub, Monzo, Stripe (Nunez), Whitespace — the operational handbook for engineer-written docs; 11-chapter lifecycle from audience research to deprecation.
- **Every Page Is Page One (Mark Baker, XML Press 2013, ISBN 978-1-937434-28-1)** — https://xmlpress.net/publications/eppo/ ; https://everypageispageone.com/
  - Foundational work on topic-based writing for the web; 7 EPPO principles (self-contained, establishes context, specific purpose, conforms to type, stays on one level, links richly, assumes qualified reader) widely cited in the field.

### Core principles

#### 1. Diátaxis 4-quadrant separation: never mix modes on one page

**Mechanism**: Classify every page as exactly one of {tutorial, how-to, reference, explanation}. Tutorials are learning-oriented (narrative, 'we'); how-tos are task-oriented (imperative, 'you'); reference is information-oriented (austere description); explanation is understanding-oriented (discursive). A page that mixes modes serves none well — split it.

**Source**: diataxis.fr: tutorials are 'learning-oriented' with goal 'not to help the user get something done, but to help them learn'; reference must be 'austere and uncompromising' with 'neutrality, objectivity, factuality'; 'It can be tempting to introduce instruction and explanation [in reference] … Instead, link to how-to guides, explanation and introductory tutorials.'

#### 2. Second-person 'you' for how-tos and reference; first-person plural 'we' only inside tutorials

**Mechanism**: How-tos and reference address the reader as 'you' to clarify agency. Tutorials use 'we…' to affirm the tutor-learner relationship ('First, do x. Now, do y.'). Never use 'we' to mean the BENE team in user-facing docs — that bleeds marketing voice in.

**Source**: Google Style: 'use second person ("you") rather than first-person plural ("we")', 'use active voice to make clear who's performing the action'. Diátaxis tutorials: 'Tutorials use first-person plural ("We…") to affirm relationship.'

#### 3. Front-load the answer; verb-first sentences; cut 'you can' and 'there is/are'

**Mechanism**: Every paragraph and every list item starts with the keyword/verb the reader is scanning for. Replace 'You can access X' with 'Access X'. Replace 'There are three tiers' with 'BENE has three tiers: …'. Put conditions before instructions.

**Source**: Microsoft Top-10: 'Most of the time, start each statement with a verb. Edit out you can and there is, there are, there were.' 'Lead with what's most important. Front-load keywords for scanning.' Google: 'put conditions before instructions, not after.'

#### 4. Shorter is always better — prune every excess word, read aloud, project friendliness with contractions

**Mechanism**: Read each paragraph aloud; if it doesn't sound like a friendly conversation, rewrite. Use it's, you'll, you're, we're, let's. Cut hedging ('arguably', 'essentially', 'simply', 'just'). Replace nominalizations ('the configuration of…') with verbs ('configure…').

**Source**: Microsoft Top-10: 'Our modern design hinges on crisp minimalism. Shorter is always better.' 'Write like you speak. Read your text aloud.' 'Use contractions: it's, you'll, you're, we're, let's.' 'Be brief … Prune every excess word.'

#### 5. Skimmable structure with descriptive headings + concept-first paragraphs

**Mechanism**: Headings use sentence case and front-load the keyword. The first sentence of every paragraph names the concept (so a reader scanning H2s + first-sentences gets the whole map). Bulleted lists for parallel items; numbered lists only for ordered steps. Three-or-fewer-word headings drop end punctuation.

**Source**: Write the Docs Principles: 'Skimmable: descriptive headings, contextual hyperlinks, and concepts early in paragraphs so readers can quickly find answers without reading prose linearly.' Microsoft: 'Skip end punctuation on titles, headings, subheadings, UI titles, and items in a list that are three or fewer words.'

#### 6. Every Page Is Page One — each topic self-contained, establishes context, links richly

**Mechanism**: Assume the reader landed via Google/search, not via TOC order. Every page opens with a 1-sentence purpose statement that answers 'what is this and who is it for'. Stays at one level of detail (don't drill into trust-ledger internals inside a CLI reference). Links richly to siblings and explanation pages but does not duplicate them.

**Source**: Baker, Every Page Is Page One (XML Press 2013): seven EPPO principles — 'Self-contained; Establishes its context; Has a specific purpose; Conforms to a type; Stays on one level; Links richly; Assumes the reader is qualified.'

#### 7. Code blocks are first-class content: runnable, language-tagged, paired with prose

**Mechanism**: Every code block must (a) be copy-pasteable and runnable as-is (no '…' ellipses in the critical path), (b) carry a language tag for syntax highlighting, (c) be paired with prose that names what it does before showing it, not after. Output blocks are separated from input. Inline code uses backticks; UI elements use bold.

**Source**: Stripe docs teardown (Moesif, Apidog, Mintlify): prose-to-code linking on hover, copy buttons, runnable Stripe Shell — 'short, focused paragraphs each tied to a specific code block'. Google Style: 'Code-related text should appear in specialized code font, while user interface elements require bold formatting.' Write the Docs ARID: include examples for common use cases but avoid drowning skimmability.

#### 8. Reference is austere description only — no instruction, no explanation, no opinion

**Mechanism**: CLI/MCP/schema reference pages list commands, options, flags, errors, types, limits — in the structure of the product itself. Each entry states facts: signature, parameters, returns, errors, example. No 'you might want to…' or 'this is useful when…' — those live in how-tos. Link out instead.

**Source**: Diátaxis Reference: 'austere and uncompromising', 'neutrality, objectivity, factuality', 'State facts about the machinery and its behaviour. List commands, options, operations, features, flags, limitations, error messages.' Food-packaging analogy: mixing marketing/opinion into reference is 'literally dangerous.'

### Applied to BENE docs

- **Problem**: Tutorials t00-t11 likely contain explanation sidebars ('Why we chose SQLite…', 'Trust ledger philosophy…') that distract from the doing-first learning arc.
  - Principle: Diátaxis: 'A tutorial is not the place for explanation.' Tutorials succeed when learners 'acquire the knowledge and skills', not when they understand the rationale.
  - Suggestion: Strip explanation prose out of t00-t11. Replace with one-line links: 'For why BENE uses SQLite, see explanation/architecture.md#why-sqlite.' Keep the tutorial narrative tight: 'First, run `bene init`. You should see `bene.db` created. Now, list agents.' Visible result every 2-3 steps. Avoid offering options ('you could also…') — pick one path and walk it.
- **Problem**: cli-reference.md, mcp-integration.md, schema.md probably blend reference tables with 'here's why this matters' prose and tutorial-style preambles.
  - Principle: Diátaxis reference must be neutral description; Baker EPPO 'stays on one level'.
  - Suggestion: Convert each command/tool/table entry to a uniform stanza: `bene checkpoint create <agent>` — one-line description, Arguments table, Flags table, Exit codes, Example (1 block), See also. Delete every 'this is useful when…' sentence — link to how-tos/checkpoints.md instead. Order entries by product structure (alphabetical within section), not by perceived importance.
- **Problem**: Docs likely overuse hedges and 'you can' constructions ('You can also use checkpoints to…', 'BENE is essentially a…', 'This is basically the…') — the AI-generated tells the stop-slop sweep is hunting.
  - Principle: Microsoft: 'Edit out you can and there is, there are, there were'; 'start each statement with a verb'; 'prune every excess word'.
  - Suggestion: Grep for `\byou can\b`, `\bthere (is|are|were)\b`, `\b(essentially|basically|simply|just|arguably)\b`, `\b(leverage|utilize|facilitate)\b` across all 41 .md files. Rewrite verb-first: 'You can create a checkpoint with…' → 'Create a checkpoint:'. 'BENE is essentially a harness' → 'BENE is a harness.' 'There are four tiers' → 'BENE has four tiers:'.
- **Problem**: architecture.md, philosophy.md, BENE2-DESIGN.md likely mix conceptual explanation with how-to fragments and reference tables (the classic 'one giant doc' antipattern).
  - Principle: Diátaxis: never mix modes. Baker EPPO: 'has a specific purpose; stays on one level.'
  - Suggestion: Split explanation pages into three jobs: (1) philosophy.md = pure explanation, prose, 'why BENE exists', Bene Gesserit lore, no commands; (2) architecture.md = explanation of the layered model, diagram-first, named subsystems link out to reference; (3) BENE2-DESIGN.md = explanation of the kernel redesign rationale. Move every code snippet into linked how-to or reference.
- **Problem**: How-to pages (checkpoints, memory, skills) probably read like tutorials — narrative with 'let's…' and 'we'll now…' — instead of task recipes for someone who already knows what they're doing.
  - Principle: Diátaxis how-to is for a competent user solving a specific problem; uses imperative 'you' voice; assumes context.
  - Suggestion: Each how-to opens with: 'This guide shows you how to <verb a specific outcome>. You should already know <prerequisite>.' Then numbered imperative steps, each ≤2 sentences, each producing a checkable result. End with 'Next: …' linking to related how-tos. Drop all 'let's', 'we'll', 'now that we've…' — those belong in tutorials.

### Red flags to catch

- **Sentences starting with 'You can …' (any verb)**
  - Why bad: Microsoft Top-10 explicitly flags this as weak writing — it adds two words, hedges agency, and delays the verb the reader is scanning for.
  - Fix: Drop 'you can' and start with the verb: 'You can create a checkpoint by running…' → 'Create a checkpoint:'. Grep: `^\s*[-*]?\s*You can `.
- **'There is / there are / there were …' constructions**
  - Why bad: Microsoft Top-10: weak writing. Pushes the real subject and verb to the end of the sentence, defeating front-loading.
  - Fix: Invert: 'There are four autonomy tiers' → 'BENE defines four autonomy tiers: L0…L4.' Grep: `\bthere (is|are|was|were) `.
- **Hedge / filler words: essentially, basically, simply, just, arguably, in essence, at the end of the day, it's worth noting that, it should be noted**
  - Why bad: Pure noise — Microsoft 'prune every excess word' and stop-slop discipline both target these as AI-tell markers.
  - Fix: Delete the word; if the sentence loses meaning, the meaning was hedged in the first place. Grep: `\b(essentially|basically|simply|just|arguably|in essence|it'?s worth noting|it should be noted)\b`.
- **Title-case headings ('Create A New Checkpoint And Restore From It')**
  - Why bad: Microsoft, Google, and most modern style guides mandate sentence case for scannability and i18n consistency.
  - Fix: Convert all H1-H6 to sentence case: 'Create a new checkpoint and restore from it'. Keep proper nouns capitalized (BENE, SQLite, MCP). Grep H2+ lines `^#{2,}\s+[A-Z]\w+ [A-Z]\w+` and audit.
- **Reference page with imperative prose ('You should set this when you want to…', 'It's recommended to…', 'A good practice is…')**
  - Why bad: Diátaxis: reference must be neutral description. Recommendation prose belongs in how-tos or explanation — mixing it into reference makes the page unreliable as a lookup surface.
  - Fix: Extract recommendations into a how-to or explanation page, link from the reference entry: 'See also: how-tos/checkpoints.md for retention strategy.' Grep reference files for `you should`, `it'?s recommended`, `a good practice`, `we recommend`.
- **Tutorial page that explains 'why' instead of guiding 'do this, now do this'**
  - Why bad: Diátaxis: 'A tutorial is not the place for explanation … Learners focused on doing get distracted by extended discussion.'
  - Fix: Move explanation paragraphs to explanation/*.md and replace with one-line link: 'For background, see explanation/architecture.md.' Keep tutorial steps verb-first, imperative, with a visible result every 2-3 steps.
- **Code blocks without language tag, or with non-runnable '…' placeholders in the critical path**
  - Why bad: Stripe-style benchmark requires copy-pasteable, syntax-highlighted code. Ellipses force the reader to guess; missing language tags break highlighters and AI assistants reading the docs.
  - Fix: Tag every fenced block (```bash, ```python, ```yaml, ```sql, ```json). Replace `…` with a real value or a clearly-named placeholder like `<agent-name>` and document it underneath.
- **Paragraphs longer than 4 sentences in how-to or tutorial pages**
  - Why bad: Stripe and Write the Docs both treat short paragraphs as a load-bearing affordance for scanning; long paragraphs hide the action verb and the result.
  - Fix: Split at the next logical action. If a paragraph describes 3 things, make it 3 paragraphs or a bulleted list. Reference pages get a stricter rule: one fact per line where possible.
- **'We' meaning the BENE team in user-facing docs (outside tutorials)**
  - Why bad: Google Style: use 'you' not 'we'. 'We' in how-tos and reference imports marketing/team voice and blurs agency — the reader wonders who's actually running the command.
  - Fix: Rewrite to 'you' or imperative: 'We recommend running…' → 'Run…' or move the recommendation to explanation/. Inside tutorials, 'we' is allowed and useful for the tutor-learner arc.
- **Marketing-tone superlatives ('powerful', 'seamless', 'robust', 'cutting-edge', 'world-class', 'state-of-the-art')**
  - Why bad: Diátaxis reference forbids opinion ('literally dangerous' to mix marketing claims into reference); Microsoft 'crisp minimalism' rejects these as filler; classic AI-slop signals.
  - Fix: Replace with a concrete capability or metric: 'powerful query layer' → 'query layer that supports full-text search across engrams up to tier 4'. Grep: `\b(powerful|seamless|robust|cutting[- ]edge|world[- ]class|state[- ]of[- ]the[- ]art|unleash|leverage)\b`.

---

## canonical Chinese tech-doc writing — structural model, tone discipline (中文工程师 voice), 段落/句长 conventions, 中英文混排排版, 翻译腔 / AI-味 anti-patterns

### Sources consulted

- **阮一峰《中文技术文档的写作规范》(2016, ruanyf/document-style-guide, public domain)** — https://www.ruanyifeng.com/blog/2016/10/document_style_guide.html  +  https://github.com/ruanyf/document-style-guide
  - the most-cited 中文 tech-doc style guide in the Chinese dev community; explicit, numeric, frequently mirrored by Baidu / Aliyun / CSDN as base spec
- **sparanoid/chinese-copywriting-guidelines —《中文文案排版指北》** — https://github.com/sparanoid/chinese-copywriting-guidelines
  - de-facto Chinese typography spec used by Vue.js zh docs, LeanCloud docs, Vite zh docs; v1.0.0 stabilized 2021-11
- **Liao Xuefeng (廖雪峰) Python / Git / Java tutorials** — https://liaoxuefeng.com/books/python/introduction/index.html
  - longest-running Chinese-language programming tutorial corpus; tone benchmark for friendly-but-precise pedagogical 中文 — talks to the reader as 你, layers concept→example→reassurance
- **Zhang Xinxu (张鑫旭) frontend blog & 《CSS 世界》** — https://www.zhangxinxu.com/wordpress/  +  book: 张鑫旭《CSS 世界》, 人民邮电出版社 2017
  - longest-running solo Chinese frontend technical blog; demo-first, short-paragraph, terminology-disciplined 中文工程师 voice with strict 中英混排 spacing
- **Vue.js 官方中文文档 — 翻译说明 (vuejs-translations/docs-zh-cn)** — https://cn.vuejs.org/about/translation  +  https://github.com/vuejs-translations/docs-zh-cn
  - the cleanest worked example of a large OSS doc translated into 中文 with explicit anti-翻译腔 conventions (markup, punctuation, term table)
- **课代表立正 / 孙煜征 — writing-method skill (locally distilled from 20+ public essays, podcasts, course notes)** — /home/admin/.claude/skills/kedaibiao-writing-method/SKILL.md  +  https://www.lizheng.ai/  +  https://www.superlinear.academy/ai-builders
  - current canonical Chinese AI-engineering essay voice — 'externalize hidden work logic into public artifacts'; explicit anti-tool-worship discipline matters for AI/工程 prose
- **Baidu Cloud Developer — 中文技术文档写作规范 (mirror of ecosystem consensus)** — https://cloud.baidu.com/article/3022535
  - represents the 阿里云/百度云 ecosystem position — 总分总 structure + terminology consistency, since Aliyun does not publish a standalone public Chinese style guide

### Core principles

#### 1. 硬上限句长 (Hard sentence-length ceiling)

**Mechanism**: Single clause / comma-separated unit ≤ 20 characters is the target; 20–29 acceptable; 30–39 only when meaning is unambiguous; ≥40 NEVER acceptable. When a draft exceeds 30, split at the first 因为/所以/而/并/同时 boundary, or extract the predicate into its own sentence. Tools-level enforcement: regex `[^，。；！？\n]{30,}` to flag candidates.

**Source**: 阮一峰: 「单个句子长度尽量保持在 20 个字以内；20～29 个字的句子可以接受；30～39 个字的句子语义必须明确才能接受；多于 40 个字的句子任何情况下都不能接受。」

#### 2. 肯定句优先、避免「被」字句 (Affirmative voice over passive / negative)

**Mechanism**: Default to subject-verb-object affirmative. Replace 「不能」「不可以」「没有...的话」with the positive form (「需...」「必须...」「请...」). Replace 「X 被 Y 完成」with 「Y 完成 X」or 「Y 处理 X」. The 「被」字句 is almost always translation-tone leakage from English passive.

**Source**: 阮一峰: 「尽量使用肯定句表达，不使用否定句表达（例如：没有、不能、不可以），不使用『被』」

#### 3. 中英文/数字之间留一个半角空格 (Mandatory pangu spacing)

**Mechanism**: Insert one half-width space between any 中文字符 and any 半角 letter/digit. Numerals stay 半角; units after numerals get one space (`10 kg`, `20 TB`), except `%` and `°` which sit flush. 中文标点全用全角，never `! ? , ; :` after Chinese text. Full-width punctuation does NOT get spacing on either side.

**Source**: sparanoid/chinese-copywriting-guidelines: 「中文與英文之間需要增加空格」「中文與數字之間需要增加空格」「數字與單位之間需要增加空格（90°、15% 例外）」+ 阮一峰: 「中文语句的标点符号，均应该采取全角符号」

#### 4. 代词必须有唯一指代 (Anaphora must resolve to exactly one antecedent)

**Mechanism**: Every 「其/该/此/这/它/那个」must point to one and only one prior noun. If two candidates are within 30 字, replace the pronoun with the noun. Especially watch 「这」at paragraph start — it is the #1 翻译腔 vector from English `this`/`it`.

**Source**: 阮一峰: 「使用代词时（比如『其』、『该』、『此』、『这』等词），必须明确指代的内容，保证只有一个含义」

#### 5. 动词优先于名词 (Verbs over noun-stacks)

**Mechanism**: When the same root can be noun or verb, choose the verb. 「请对 X 做一些修改」→「请修改 X」. 「进行了优化」→「优化了」. 「实现了对...的支持」→「支持...」. For AI/工程 prose specifically (kedaibiao): if a paragraph is dominated by nouns (RAG / LangChain / MCP / agent / pipeline), rewrite so each noun becomes a component inside a working verb chain (拆解 → 路由 → 评测 → 落库).

**Source**: 阮一峰: 「某些词语既可名词也可动词的时候，可以优先考虑动词」+ kedaibiao-writing-method §5 'Use Verbs As The Real Curriculum'

#### 6. 具体场景先行，再抽象 (Concrete scene before concept)

**Mechanism**: Open every section from a recognizable work scene (a command that broke, an output that looked plausible but wasn't, a setup step that wedged). Only name the concept after the reader has seen the problem. Liao Xuefeng uses the same pattern with 你 + rhetorical question: 「你也许会问，X 不就行了？」then earns the abstraction.

**Source**: kedaibiao-writing-method §1 'Concrete Before Concept' + 廖雪峰 introduction pattern (rhetorical 你-question before abstraction)

#### 7. 总—分—总结构 + 三级以内标题 (Overview→detail→summary with shallow hierarchy)

**Mechanism**: Each doc opens with one paragraph stating what the reader will be able to do, body breaks into parallel sections under H2/H3 only (avoid H4+), closes with a short 「下一步」or 「不在范围内」block. Lists are used for parallel items under H3; if items are not truly parallel, write prose instead.

**Source**: 阮一峰: 「使用一二三级标题组织内容，三级标题下面的并列性内容使用列表展示」+ 百度云镜像: 「建议采用总分总的结构」

#### 8. 术语首现给中英对照，之后保持一致 (Term-table discipline)

**Mechanism**: First occurrence: 中文译名（English Original，可选解释）, e.g. 「检查点（checkpoint，写入前快照）」. After that, pick ONE form (中文 or English) and stick to it across the entire document; mixing forms within a doc is a stronger 翻译腔 signal than either pure form. Proper-noun casing is preserved exactly: GitHub / JavaScript / MySQL — never github / Javascript / Mysql.

**Source**: 阮一峰: 「第一次出现英文词汇时，在括号中给出中文标注」+ sparanoid: 「使用 GitHub 登錄」(正) vs 「使用 github 登錄」(误) + Vue zh translation conventions

### Applied to BENE docs

- **Problem**: Hero block in site/index.html zh dict mixes 「上一次」 / 「git stash」 / 「这工具」 in fast succession; the 「这工具」 antecedent leans on the English handle, not a Chinese noun. Risk: reader who jumps into the page mid-sentence loses the referent.
  - Principle: 代词必须有唯一指代 + 术语首现给中英对照
  - Suggestion: First mention writes the Chinese term once: 「BENE（本地 SQLite 多 agent 朮架）」. After that, refer to it as 「BENE」or 「这套朮架」—never 「这工具」 (too generic; could mean Claude Code / Cursor / Aider already mentioned). Specifically: hero.forWho 「上一次 agent 改炸 prod、你 git stash 一回头发现栈是空的——这工具写给你。」→ 「上一次 agent 改炸 prod、你 git stash 回头发现栈是空的——BENE 写给你。」
- **Problem**: Several zh blocks contain clauses well over 30 characters between commas, e.g. interop.body: 「37 个工具走 MCP / stdio，agent 配置里加一行。同一套表面也支持 --json，jq 直接吃。Claude Code、Cursor、Aider 共用同一份 bene.db——不必给每个 IDE 各写一遍适配器。」 The last clause (不必给每个 IDE 各写一遍适配器) is borderline but the surrounding ones risk drift on rewrites.
  - Principle: 硬上限句长 + 动词优先于名词
  - Suggestion: Run a sentence-length lint in CI on every zh dict value: regex `[^，。；！？\n]{30,}` flags candidates; rewrite to verb-led short clauses. Pattern: lead with the verb the reader will execute. For build.recipes[0].getYou 「每次跑都是一个 checkpoint，每次 diff 都在本地，一条命令滚回到 green。」— already good. Apply same rhythm everywhere: 3–4 short clauses, last clause is the payoff.
- **Problem**: Mixed punctuation register: zh dict uses some half-width commas inside code captions/snippets (acceptable in code) but also leaks into prose strings, e.g. `'不靠 git、不靠在线服务、不靠云。整条 rewind 就在那份本地 SQLite 里。'` is correct — but other places (older v1 surfaces left in dict) still mix `Litany Against Fear` with no pangu space before/after. Pangu-spacing is inconsistent across the dict.
  - Principle: 中英文/数字之间留一个半角空格
  - Suggestion: Add a pre-commit hook running `pangu.py` (or a 5-line Python: `re.sub(r'([一-鿿])([A-Za-z0-9])', r'\1 \2', s)` + inverse) over `site/index.html` zh-block string literals. Then a second pass that flags any half-width `,.!?;:` immediately following a CJK char in the zh dict. Both produce zero false positives on engineer prose because the dict is short.
- **Problem**: origin block leaks slogan-tone: 「BENE 是个 backronym...但起名的时候先用的是 Dune 里的 Bene Gesserit」— then drifts toward 「这跟 checkpoint / diff / restore 的循环对得上」which is honest but the surrounding mythology lines risk feeling decorative if a future edit thickens them. Watch for slogan creep on next rewrite.
  - Principle: kedaibiao 'Do Not overuse inspirational slogans' + 阮一峰 禁口语化
  - Suggestion: Keep the rule: every Bene Gesserit reference in zh prose must be followed within the same paragraph by a concrete BENE artifact (`bene.db` row, CLI verb, `assets/demos/*.gif`, sha256 in PREREG.md). If a future edit adds a mythology line without an artifact pair within 2 sentences, revert. Encode this as a `docs/zh-rewrite/INVARIANTS.md` rule for the next zh-rewrite pass.
- **Problem**: Light-verb constructions creeping into the zh dict on the docs/ side, especially in cli/mcp surfaces — patterns like 「实现对 X 的支持」「进行检查点」 are the highest-yield single sweep.
  - Principle: 动词优先于名词
  - Suggestion: Single-sweep regex over the zh dict (and any zh markdown if added later): `(进行|做|实现|完成)了?[一-鿿]{1,4}`. Replace mechanically: 「进行检查点」→「建检查点」, 「实现对 MCP 的支持」→「支持 MCP」, 「完成 turn 的回滚」→「回滚 turn」. Saves 2–4 chars per hit and sounds like an engineer, not a translator.

### Red flags to catch

- **「被」字句 — regex: `[^一]被[一-鿿]{1,6}(了|的|过)`**
  - Why bad: Direct passive-voice carryover from English; 阮一峰 explicitly bans it; native 中文工程师 voice prefers affirmative ('内核拦下了越权动作' not '越权动作被内核拦下了')
  - Fix: Invert to active SVO. If the agent is unknown, restate the system as subject. Acceptable exception: legal/compliance phrasing like 「被判定」— but in BENE docs there is no such case.
- **Clause/sentence > 30 字 between commas/periods — regex: `[^，。；！？\n]{30,}`**
  - Why bad: 阮一峰 hard rule. Long clauses correlate strongly with MT/AI output and force readers to re-parse. Real 中文工程师 prose (Liao Xuefeng, Zhang Xinxu) averages 12–18 字 per clause.
  - Fix: Split at the first 因为/所以/而/并/同时/通过 boundary. If still long, extract the predicate ('实现了对 X 的支持' → '支持 X').
- **Missing pangu space — regex: `[一-鿿][A-Za-z0-9]` or `[A-Za-z0-9][一-鿿]`**
  - Why bad: Spec violation per sparanoid 指北 and 阮一峰; visually merges 中英 tokens; signals the writer didn't proof the file in a rendered viewer.
  - Fix: Insert one half-width space between every 中文/拉丁字母-数字 boundary. Exception: punctuation (`，。`) and unit-flush forms (`90°`, `15%`). Run `pangu.py` or equivalent in CI.
- **Half-width punctuation after Chinese — regex: `[一-鿿][,.!?;:]` (NOT `，。！？；：`)**
  - Why bad: Reads as un-localized English; sparanoid 指北 calls this out explicitly; one of the strongest cosmetic 翻译腔 tells.
  - Fix: Replace with the 全角 equivalent (`，。！？；：`). Configure editor to auto-convert when previous char is 中文.
- **Floating 「这」/「这些」/「它」at paragraph or sentence start with antecedent > 1 sentence back**
  - Why bad: Direct calque of English `This`/`These`/`It` paragraph openers; 阮一峰 explicit rule that 代词 must have exactly one antecedent. In zh tech writing 中文 prefers re-stating the noun, not chaining pronouns.
  - Fix: Replace 「这」with the actual noun ('这套机制' → '检查点机制' or '上面那条命令'). If the antecedent ambiguity is real, restate it inside the sentence.
- **Noun-stack openings (3+ nouns before the first verb), especially English-jargon stacks like 'RAG + agent + workflow + pipeline'**
  - Why bad: kedaibiao explicit anti-pattern — 'if a draft is dominated by nouns (RAG/LangChain/MCP/agent), rewrite so the nouns become components inside a working verb chain.' Noun-heavy openings signal tool-worship over real method.
  - Fix: Lead with the verb chain (拆解 → 路由 → 评测 → 落库), demote tool names to parens or footnotes. Ask: what does the reader DO differently tomorrow?
- **Empty intensifiers / hedge phrases — 「非常」「极其」「显著地」「相对来说」「在某种程度上」「值得注意的是」**
  - Why bad: Both 阮一峰 (口语化禁令) and the 张鑫旭 / 廖雪峰 voice strip these; they are the strongest AI-味 tell after pangu-space violations because LLMs sprinkle them as default padding.
  - Fix: Delete the qualifier. If a number is the basis ('non-trivially faster'), give the number. If not, the qualifier was hiding the absence of a claim.
- **进行/做/实现/完成 + 名词 (light-verb constructions) — regex: `(进行|做|实现|完成)了?[一-鿿]{1,4}`**
  - Why bad: 阮一峰 verb-priority rule; pattern is 'do-X' calque from English Latinate verbs; 「进行优化」 = 「优化」, 「实现了对 X 的支持」 = 「支持 X」.
  - Fix: Strip the light verb; promote the noun to verb. Saves 2–4 chars per occurrence and reads as native engineer prose.
- **Slogan sentences with no operational follow-up — '让 AI 真正为你工作', '释放生产力', '赋能开发者'**
  - Why bad: kedaibiao 'Do Not overuse inspirational slogans'; also marketing-tone, which violates the engineer-voice discipline of 张鑫旭 / 廖雪峰.
  - Fix: Replace with an artifact + action: 'agent 写过的每一行字节都落到 bene.db，下一个 agent grep 出来。' Concrete object + concrete verb beats every slogan.
- **Mixed punctuation register in one document — some 句号 are `.`, some are `。`; some 引号 are `""`, some are `「」`**
  - Why bad: Vue.js zh translation guide + sparanoid both fail any doc that mixes registers — it's the clearest signal of MT/AI pasting in foreign text without normalization.
  - Fix: Pick one convention per doc (recommend: 全角 句号 + 全角 引号 `「」` for 简体). Lint with a script that flags any half-width terminal punctuation immediately after a CJK char.

---

## structural-clarity-for-technical-prose

### Sources consulted

- **Steven Pinker — The Sense of Style (Penguin, 2014), esp. ch. 2 'A Window onto the World' (classic style), ch. 3 'The Curse of Knowledge', ch. 4 'The Web, the Tree, and the String'** — https://sive.rs/book/SenseOfStyle ; https://www.supersummary.com/the-sense-of-style/summary/
  - Pinker is a cognitive psychologist and Harvard linguistics chair; book is the most cited cognitive-science-grounded modern style manual.
- **Joshua Schimel — Writing Science (Oxford UP, 2012), ch. 4 OCAR + ch. 5 ABDCE / LDR variants** — http://tlmerrill.pbworks.com/w/file/fetch/110502724/Writing%20Science%20J.%20Schimel%202012.pdf ; https://ntthung.wordpress.com/2018/05/08/writing-science-a-book-by-joshua-schimel/
  - Schimel is a UC Santa Barbara ecologist; the book is the de-facto manual taught in NSF/NIH writing workshops for science-paper structure.
- **William Zinsser — On Writing Well (HarperCollins, 30th anniv. ed.), ch. 2 'Simplicity', ch. 4 'The Lead and the Ending', ch. 10 'Bits & Pieces', ch. 16 'Business Writing', ch. 17 'Science and Technology'** — /home/admin/gh/bene-main/docs/research/product-comms/on-writing-well.md (already-distilled) ; https://nysba.org/thoughts-on-legal-writing-from-the-greatest-of-them-all-william-zinsser/
  - Zinsser taught nonfiction at Yale and Columbia; book is the canonical 'clutter as disease' source, already distilled in-tree at the cited path.
- **William Strunk Jr. & E.B. White — The Elements of Style, 4th ed. (Pearson, 2000), Principles of Composition rule 'Omit needless words' (rule 13/17 depending on edition)** — https://ia801500.us.archive.org/26/items/pdfy-2_qp8jQ61OI6NHwa/Strunk%20&%20White%20-%20The%20Elements%20of%20Style,%204th%20Edition.pdf ; https://news.cornell.edu/node/272696
  - Strunk taught the rule at Cornell from 1899; >10M copies sold; 'every word tell' formulation is the canonical brevity principle in English composition pedagogy.
- **John Sweller — 'Cognitive Architecture and Instructional Design' (Educ. Psych. Review, 1998, w/ van Merriënboer & Paas) + 'Cognitive load theory, learning difficulty, and instructional design' (Learn. Instr. 4: 295-312, 1994) + Sweller & Cooper 1985 worked-example studies** — https://link.springer.com/article/10.1023/A:1022193728205 ; https://www.instructionaldesign.org/theories/cognitive-load/ ; https://en.wikipedia.org/wiki/Cognitive_load
  - Sweller (UNSW) is the originator of Cognitive Load Theory; peer-reviewed and replicated worked-example effect is the empirical basis for chunking + sequencing recommendations.
- **Donald E. Knuth, Tracy Larrabee, Paul M. Roberts — Mathematical Writing (MAA Notes #14, 1989; earlier STAN-CS-88-1193, Jan 1988)** — https://www-cs-faculty.stanford.edu/~knuth/papers/cs1193.pdf ; https://www-cs-faculty.stanford.edu/~knuth/klr.html
  - Transcript of Knuth's Stanford CS 209 (autumn 1987) with guest lectures from Halmos, Lamport, Ullman, van Leunen — primary-source style rules for technical/mathematical exposition by the author of TAOCP and TeX.
- **Brian W. Kernighan & Rob Pike — The Practice of Programming (Addison-Wesley, 1999), ch. 1 'Style' §1.1 Names, §1.6 Comments, §1.7 Why Bother?** — https://theswissbay.ch/pdf/Gentoomen%20Library/Software%20Engineering/B.W.Kernighan,%20R.Pike%20-%20The%20Practice%20of%20Programming.pdf ; https://en.wikipedia.org/wiki/The_Practice_of_Programming
  - Kernighan co-authored K&R C; Pike co-designed Plan 9, UTF-8, and Go. Bell Labs operating-system pedigree makes ch. 1 the canonical 'naming + comments as docs' source for systems code.

### Core principles

#### 1. Classic style: writing as a window, not a performance

**Mechanism**: Frame every paragraph as the writer pointing the reader's gaze at something concrete in the world that the reader can verify. Banish self-conscious meta ('this paper will discuss…', 'we now turn to…') and hedging meta ('it is generally believed that…'). Treat reader as an intellectual equal looking at the same artifact (a SQLite row, a benchmark plot, a failing trace). Works identically in EN and 中文 because the move is structural — point at the artifact — not lexical.

**Source**: Pinker, The Sense of Style ch. 2: 'the writer can see something that the reader has not yet noticed and he orients the reader's gaze so that she can see it for herself.' (supersummary, sivers summaries)

#### 2. Curse of knowledge: assume the reader has none of your context

**Mechanism**: Before any technical claim, ask: what does the reader need to already know for this sentence to land? Then either (a) supply that prerequisite in the prior sentence, or (b) link to a one-paragraph primer. Specifically: expand acronyms on first use; replace house jargon ('engram', 'tier-0', 'kill-gate') with a 5-word gloss the first time it appears in each doc; have an outsider read the draft. Translation-invariant: the cognitive bias is universal, not English-specific.

**Source**: Pinker ch. 3: 'a difficulty in imagining what it is like for someone else not to know something that you know … the single best explanation … of why good people write bad prose.' Remedy: 'get people who are NOT experts in your field to read your work and tell you whether or not it's accessible.'

#### 3. Tree-to-string: write left-heavy, light-right; resolve syntactic suspense fast

**Mechanism**: The reader receives words as a 1-D string but must reconstruct a tree in working memory. Reduce that load by: (1) putting the subject + verb early; (2) avoiding deep noun pre-modification stacks ('the meta-harness search loop generation kill-gate threshold' → 'the threshold the kill-gate applies during a meta-harness search'); (3) closing brackets fast — never leave a clause hanging across 30+ words; (4) one new idea per sentence. Translation-invariant: 中文 has the same working-memory bottleneck and suffers even more from long pre-modifier '的'-chains.

**Source**: Pinker ch. 4 'The Web, the Tree, and the String' — ideas exist as a web; language is a string; the tree mediates. Critiques: 'subject-verb mismatches, noun piles, and syntactic ambiguity.'

#### 4. OCAR / story arc at every altitude (page, section, paragraph)

**Mechanism**: Every unit — landing page, doc page, section, even a 3-paragraph block — gets an Opening (who/where/what's at stake), Challenge (the specific question), Action (what you did), Resolution (what changed, linking back to O). The R must match the width of the O — no overpromising, no underselling. For BENE-style design rationale docs: open with the failure mode the design fixes; pose the question the design answers; walk the mechanism; resolve by showing the failure now doesn't happen. Translation-invariant: narrative shape is independent of language.

**Source**: Schimel, Writing Science ch. 4: 'OCAR is principle, IMRaD is rule. Intro = OC; Methods and Results = A, and Discussion = R.' Hourglass shape (Fig 4.2): 'If O is wider than R, you are overpromising and underdelivering.' 'The story structure does not apply only to the paper as a whole, but for each part of it too.'

#### 5. Omit needless words — every word must tell

**Mechanism**: Brackets test (Zinsser's bracket-the-clutter operationalization of Strunk): mark every modifier, qualifier, and redundancy in a draft; if the sentence still holds after deletion, delete. Specific targets: 'in order to', 'the fact that', 'a number of', 'somewhat', 'really', 'basically' (EN); '进行', '的相关', '通过…的方式', '在…方面', '所…的' (中文 equivalents). Translation-invariant: padding has different surface forms but identical function — disguising lack of content.

**Source**: Strunk & White, Elements of Style: 'Vigorous writing is concise. A sentence should contain no unnecessary words … not that the writer make all sentences short … but that every word tell.' Zinsser ch. 2 operationalizes via brackets (on-writing-well.md §Reader brain moves).

#### 6. People-doing-things over concept-noun chains

**Mechanism**: Replace nominalized abstractions ('the optimization of context utilization') with a concrete actor + active verb ('the router throws out cached prompts older than 4 turns'). In design docs this means: name the subsystem, name the operation, name the artifact it acts on. 中文 equivalent: 用具体主语 + 实动词 替换 抽象名词 + '的' + 抽象名词 链. Translation-invariant because the cognitive payoff is visualization — the reader sees an actor act.

**Source**: Zinsser ch. 10 'Bits & Pieces': 'the common reaction is incredulous laughter' vs 'most people just laugh with disbelief' — 'no people in them and no working verbs'. Pinker ch. 4 critiques 'noun piles'. (Both already distilled in /docs/research/product-comms/on-writing-well.md §Anti-pattern 1 & 2.)

#### 7. Cognitive load: chunk into 4-7 elements; lead with worked examples for novices

**Mechanism**: Working memory holds ~4-7 items. (1) Cap any list/step-sequence at that size; nest deeper sub-points instead of flattening. (2) For a novice audience (most landing visitors), open with a worked example — a full end-to-end trace they can copy-run — before stating the abstract principle. (3) Distinguish intrinsic load (the inherent topic difficulty) from extraneous load (how you laid it out): minimize the latter by removing split-attention (don't make the reader hold a diagram in one tab and prose in another — inline the artifact). (4) Beware the expertise-reversal effect: worked examples that help beginners hurt experts; give experts a skip-link to the reference.

**Source**: Sweller, van Merriënboer & Paas 1998 (Springer Educ. Psych. Review): three load types (intrinsic/extraneous/germane) + worked-example effect + split-attention effect. Sweller & Cooper 1985 algebra study. 'Learners with low prior knowledge can benefit more from studying worked examples rather than solving problems themselves.' Miller 1956 7±2 chunk limit.

#### 8. Naming and comments are documentation; bad code can't be saved by comments

**Mechanism**: (1) Names carry information density: use specific, pronounceable nouns/verbs; reserve short names for short scopes. (2) Comments explain *why* and *what for*, not *what* — the code already says what. (3) Don't belabor the obvious, don't contradict the code, don't comment bad code (rewrite it). (4) Document interfaces (function signatures, struct layouts) heavily; document internals sparsely. For BENE specifically: schema column comments + CLI flag help-text are first-class docs; if they disagree with prose, prose loses. Translation-invariant because naming and signature discipline are language-agnostic — they're about the artifact, not the gloss.

**Source**: Kernighan & Pike, Practice of Programming ch. 1: 'Don't belabor the obvious. Comment functions and global data. Don't comment bad code, rewrite it. Don't contradict the code. Clarity, don't confuse.' §1.5: 'Give names to magic numbers.' Knuth/Larrabee/Roberts §1 minicourse: name choice and notation discipline as the foundation of mathematical exposition.

### Applied to BENE docs

- **Problem**: Architecture/design pages open with abstract framing ('BENE gives each agent a private filesystem, a replayable event trail…') before the reader knows why they should care. Classic curse-of-knowledge tell — author already knows the value prop and assumes reader does too.
  - Principle: Curse of knowledge + OCAR Opening: stake before structure
  - Suggestion: Open with the failure the architecture fixes, not with the architecture: 'Your agent corrupts the working tree mid-turn. git stash won't help — it never wrote those files to git. BENE checkpointed before that turn; one bene restore rewinds it. The next three sections show how — request flow, stored state, then subsystem boundaries.' That is O(failure)→C(how do we rewind?)→A(diagram)→R(corruption is reversible). Same move works in 中文: 把失败摆在最前面，把架构放在为失败服务的位置.
- **Problem**: Design-rationale docs (e.g., DESIGN-RATIONALE.md, KERNEL-SPEC.md) likely lean on concept-noun chains: 'the kernel's engram compression ladder's tier-0 retention policy'. Reader cannot visualize who-acts-on-what.
  - Principle: People-doing-things over concept-noun chains (Zinsser/Pinker tree-to-string)
  - Suggestion: Rewrite as actor-verb-object chains with the artifact named: 'When the agent emits a trace event, the kernel writes it to tier-0. Every 100 events, the compressor rolls tier-0 into tier-1 and drops anything not referenced by a live probe.' 中文 同构: '智能体写一条 trace，kernel 进 tier-0；每攒 100 条，compressor 把 tier-0 卷成 tier-1，没被 probe 引用的就丢。' Both versions: subject does verb to object — reader sees the action.
- **Problem**: Benchmark/claims docs (RIVAL-BENCH-REPORT.md) likely present numbers without OCAR — table dump then conclusion, or conclusion then table dump, with no Challenge framing. Reader doesn't know what question the number answers.
  - Principle: OCAR at section altitude + R must match O
  - Suggestion: Each benchmark section: O = the specific operational question ('Can BENE recover from a poisoned context within one turn?'), C = how a failure would look ('the agent keeps emitting the bad pattern; trust score never recovers'), A = the experiment ('we injected pattern X at turn 5 across 50 runs; sweep ran at turn 6'), R = the resolved number that answers O ('trust returned to baseline in 47/50; median 1.2 turns'). R width = O width: if O promises 'recovery within one turn' and R says 'median 1.2 turns', say so explicitly — don't hide the gap. Works in 中文 unchanged.
- **Problem**: Heavy technical-claim density without worked examples — sections that state mechanism after mechanism without ever running one. This blows past 7±2 working-memory limit and gives the reader no schema to hang the next claim on.
  - Principle: Cognitive load: chunk + worked example before abstraction
  - Suggestion: Before any 3+ mechanism description, insert a 5-line worked example with copy-pasteable commands and expected output. E.g., before describing the engram compression ladder, show: '$ bene demo --trace-tier 0,1,2 → events 1-100 in tier-0; at event 101 → tier-0 rolls to tier-1, you see "rolled 100→tier-1" in stderr; ...'. Then the abstract ladder description hangs on that concrete schema. Cap each mechanism list at 5-7 items; if more, nest. 中文 同理: worked example 一定要给真实命令和真实输出，不能用 '示意' 替代.
- **Problem**: Prose hedging and padding in claim-dense docs: 'BENE can potentially help agents recover from various forms of context pollution by leveraging its checkpoint-based restoration mechanism.' (hypothetical but typical). Every modifier is doing PR, not work.
  - Principle: Omit needless words + classic style
  - Suggestion: Strip: 'BENE rewinds a poisoned context. bene restore --turn N drops the agent state back to turn N; the next turn starts from there.' Deleted: 'can potentially', 'help … recover from', 'various forms of', 'by leveraging', 'mechanism'. 5 commission verbs replaced 1 weasel verb. 中文 strip: '把 "BENE 可以通过 checkpoint 机制对受污染的上下文进行恢复" 改成 "BENE 把污染的上下文倒回去：bene restore --turn N，agent 从第 N 轮重启"'. Strip 通过/进行/对…的/机制 four-piece chain — 它们不干活.

### Red flags to catch

- **Sentence opens with 'It is …', 'There is/are …', 'This [noun] …' as a topical placeholder; or 中文 opens with '这[名词]…','所谓[术语]…','对于…而言'.**
  - Why bad: Pinker classic-style violation: meta-commentary instead of pointing at the artifact. Wastes the slot where the actor should go. Also typically signals nominalization downstream.
  - Fix: Promote the real actor to subject: 'It is important to checkpoint before mutations.' → 'Checkpoint before any mutation. The restore command depends on it.' / '对于上下文污染而言，BENE 提供了…' → 'BENE 把污染的上下文倒回去：…'
- **Noun pile of 3+ nouns or 3+ '的': 'meta-harness search candidate evaluation threshold' / 'kernel 的 trace 的 tier 的 retention 策略'.**
  - Why bad: Pinker tree-to-string failure: reader has to backtrack to figure out which noun modifies which. High working-memory cost. Worse in 中文 because '的'-chains nest right-to-left.
  - Fix: Break into a verb-bearing clause: 'the threshold the search loop uses to evaluate candidates' / 'kernel 给每层 trace 配的 retention 策略 — tier-0 留全部，tier-1 留 100 条，tier-2 留 hash'.
- **Paragraph or section ends without resolving the question its opener raised (no R for the O), or R is narrower/wider than O.**
  - Why bad: Schimel OCAR violation: reader feels cheated or oversold. Especially fatal in claim-dense benchmark prose where R is the number the reader came for.
  - Fix: Add the explicit resolution sentence: 'So <answer to opening question>: <number/outcome>.' If R doesn't match O's width, fix one of them — narrow the promise or broaden the evidence.
- **Conceptual cascade longer than 7 items without a worked example, command, or diagram in between.**
  - Why bad: Sweller cognitive-load violation: blows past working-memory chunking limit. Reader loses the thread of claim 1 by claim 5.
  - Fix: Insert a copy-runnable worked example after every 4-5 abstract claims. The example becomes the schema the next claims attach to. If you can't write the example, the abstraction isn't ready to ship.
- **Hedge stack: 'can potentially help', 'may sometimes', 'is generally believed to', 'tends to often' / '可能可以', '一般来说', '通常情况下', '在某种程度上'.**
  - Why bad: Strunk/Zinsser violation: every hedge is a word that doesn't tell. In a claim-density doc, hedges signal either (a) the author isn't sure (then say so explicitly with a number/caveat) or (b) corporate fear (Zinsser's diagnosis).
  - Fix: Either make the claim load-bearing ('rewinds the context in 47/50 cases tested') or downgrade it to a footnote. Delete all 'potentially/可能/一般' if the next clause already qualifies.
- **Comment or doc paragraph restates what the code/signature already says: 'The spawn() function spawns an agent.' / 'spawn(name): 用于 spawn 一个 agent'.**
  - Why bad: Kernighan-Pike violation: 'Don't belabor the obvious. Don't contradict the code.' Comment carries zero new information.
  - Fix: Replace with the *why*: 'spawn() — creates an isolated VFS so two parallel agents can't corrupt each other's working tree. Called by MCP agent_spawn and CLI bene spawn.' / 'spawn(name): 给每个 agent 一份隔离 VFS，并行跑不互相覆盖。MCP 和 CLI 都调它。'
- **House jargon used without first-use gloss: 'engram', 'kill-gate', 'tier-0', 'kernel', 'sweep' — repeated 5+ times before any one-line definition.**
  - Why bad: Pinker curse-of-knowledge violation. The author has internalized the term; the new reader cannot decode it. Especially bad for a project whose lore (Bene Gesserit) adds another decoding layer.
  - Fix: On first appearance per doc: '<term> (one-line gloss — the concrete thing it does)'. E.g., 'engram (a single searchable trace event written to bene.db)'. Then use the term freely. Maintain a glossary page linked from every doc header.
- **Long passive constructions or '被'-heavy 中文: 'checkpoints are written every turn' / 'context 在每一轮被压缩'.**
  - Why bad: Zinsser active-verb violation. Passive hides the actor; reader can't form the people-doing-things picture. 'By Joe' becomes invisible.
  - Fix: Name the actor and use the active verb: 'BENE writes a checkpoint every turn' / 'kernel 每一轮压一次 context'. Exception: passive is fine when the actor is genuinely unknown or genuinely irrelevant — but in BENE docs, every actor is known.

---

## Human-vs-AI-slop voice in modern dev tool docs (2023-2026): sentence-level signals, structural patterns of exemplary docs, AI-slop tells, applied to BENE

### Sources consulted

- **Stripe API Reference** — https://docs.stripe.com/api
  - Industry-defining benchmark for dev docs since 2014; side-by-side request/response; constraint-first voice ('The Stripe API doesn't support bulk updates. You can work on only one object per request.') — what most B2B dev tools try to clone.
- **Tailwind CSS Docs — Styling with utility classes** — https://tailwindcss.com/docs/styling-with-utility-classes
  - Canonical 'look up, copy, ship' reference. Live example → code → only-then explanation. Acknowledges friction ('In practice this isn't the problem you might be worried it is') instead of hand-waving past it.
- **Next.js / Vercel App Router docs** — https://nextjs.org/docs/app/getting-started
  - Cited case study of a Diátaxis-shaped restructure: explicit Getting Started → Reference → Guides split; each linked section opens with a single concrete verb-phrase ('Learn how to fetch data and stream content that depends on data.').
- **PostgreSQL official docs** — https://www.postgresql.org/docs/current/tutorial-start.html
  - 30-year-running canonical reference. Terse, declarative, zero marketing, zero CTA. The unhedged 'Chapter 1. Getting Started' header is the style in one line.
- **Diátaxis framework — tutorials & reference modes** — https://diataxis.fr/tutorials/  + https://diataxis.fr/reference/
  - Procida's framework explicitly prescribes voice per mode: tutorial uses 'we / first / now', reference is 'austere and uncompromising… neutrality, objectivity, factuality.' Adopted by Django, Cloudflare, GitLab, Gatsby, Next.js.
- **Stripe Press / Stripe writing culture (Mintlify, Slab, KnowledgeOwl write-ups)** — https://www.mintlify.com/blog/stripe-docs ; https://slab.com/blog/stripe-writing-culture/ ; https://www.knowledgeowl.com/blog/posts/code-examples-shine-like-stripe
  - Document Stripe's two core rules: 'treat code like writing — code has a style guide too' and audience-first hiring ('I know when I'm dealing with a natural writer when they ask: who is the audience?').
- **Hamming, The Art of Doing Science and Engineering (Stripe Press reissue)** — https://worrydream.com/refs/Hamming_1997_-_The_Art_of_Doing_Science_and_Engineering.pdf (preface + Ch 'You Get What You Measure')
  - Hamming's own framing in the preface — 'I will show you my style as best I can, but you must finally create your own style' — plus Shannon-via-Hamming: information = surprise. Direct license to delete sentences that contain no surprise.
- **Simon Willison — slop framing + 'edit out the made-up rationale'** — https://simonwillison.net/tags/llms/ ; https://simonw.substack.com/p/how-i-use-llms-to-help-me-write-code
  - Willison coined/popularized 'slop' for unwanted AI output and gives a concrete editing rule for LLM-drafted docs: strip sentences like 'This is designed to help make code easier to maintain' — invented rationale the model had no grounds to assert.
- **Charlie Guo — Field Guide to AI Slop** — https://www.ignorance.ai/p/the-field-guide-to-ai-slop
  - Catalogs the visible 2025 tells: em-dashes-as-default, 'It's not X. It's Y.' reflex, monotone sentence length, vapid transitions ('As technology continues to evolve…'), emoji-formatted lists in technical contexts.
- **Ozigi — Banned-Lexicon Validator (2026)** — https://blog.ozigi.app/blog/stopping-ai-slop-in-production-banned-lexicon-validator
  - Production regex/lexicon list shipped against AI slop: 6 categories — vocabulary tells (delve/tapestry/robust), corporate fluff (cutting-edge/game-changer), AI tells (at its core / plays a significant role / in today's fast-paced), affirmation tells (Certainly! / Here is / Let's explore), engagement-bait closers, structural patterns (bold-colon prefix, em-dash, contrast structures). Directly greppable.
- **Measuring AI 'Slop' in Text — arXiv 2509.19163** — https://arxiv.org/html/2509.19163v2
  - Peer-grade evidence that LLM output has measurably narrower sentence-length variance, flatter sentiment arc, repeated syntactic POS templates — i.e., the rhythm itself is a tell, not just the vocabulary.

### Core principles

#### 1. Audience-first (Stripe's hiring filter): every paragraph names a reader and a verb

**Mechanism**: Before writing a section, answer two questions in one line: who is reading this (operator running a probe? library author embedding bene?), and what will they do in the next 60 seconds (run a CLI, paste a snippet, decide between two options). If you cannot answer both, delete the section. Replaces 'BENE is a local-first multi-agent orchestration framework…' with 'You want to checkpoint an agent before a risky migration. Run this.'

**Source**: Mintlify on Stripe — Larry: 'I know when I'm dealing with a natural writer when they ask: who is the audience?' (https://www.mintlify.com/blog/stripe-docs)

#### 2. Constraint-first, not capability-first

**Mechanism**: Open feature pages with what the feature WON'T do, in one declarative sentence — then show the workaround. Stripe: 'The Stripe API doesn't support bulk updates. You can work on only one object per request.' This is the single sharpest human tell: an LLM almost never volunteers a limit; it sells. Apply it as: every doc page must have one sentence that begins 'X does NOT…' or 'X only…' within the first 5 lines.

**Source**: Stripe API docs (https://docs.stripe.com/api); cross-reference Tailwind 'In practice this isn't the problem you might be worried it is…' (https://tailwindcss.com/docs/styling-with-utility-classes)

#### 3. Diátaxis split — one voice per mode, never mixed on a page

**Mechanism**: Tutorial pages: 'we / first / now / notice that' + completable in one sitting. How-to pages: imperative + scoped to one task. Reference pages: 'austere and uncompromising… neutrality, objectivity, factuality' — no 'we', no 'imagine', no narrative. Explanation pages: prose, free to opine. The BENE failure mode is collapsing all four into one page (e.g. checkpoints.md opens with explanation, then tutorial, then reference, then a philosophy bumper-sticker). Split or label them.

**Source**: Diátaxis reference mode: 'austere and uncompromising… neutrality, objectivity, factuality' (https://diataxis.fr/reference/); tutorials mode: 'First, do x. Now, do y.' (https://diataxis.fr/tutorials/)

#### 4. Code is the load-bearing unit; prose is scaffolding around the code

**Mechanism**: Stripe's house rule — 'treat your code like your writing; have a style guide for it.' Every doc page should be readable by scanning only the code blocks. Prose between code blocks earns its place by (a) naming the next snippet's purpose in one half-sentence, (b) flagging one gotcha you'd hit, or (c) linking to the canonical reference. Anything else is filler. Tailwind's 'live example → code → only-then-explanation' is the discipline.

**Source**: KnowledgeOwl on Stripe code style (https://www.knowledgeowl.com/blog/posts/code-examples-shine-like-stripe); Tailwind docs structure (https://tailwindcss.com/docs/styling-with-utility-classes)

#### 5. Information = surprise (Hamming/Shannon): delete any sentence whose content the target reader could have written themselves

**Mechanism**: After draft, mark every sentence: does it tell the reader something they did NOT already assume? If 'BENE provides robust orchestration for modern AI agents' → reader already assumed it, delete. Keep sentences carrying non-obvious load: 'Restore is pure SQL — bene rewrites the agent's file rows and state rows — so it lands in milliseconds however much changed.' That sentence is surprise-dense; it's why checkpoints.md works.

**Source**: Hamming preface + Shannon-via-Hamming on information as surprise (https://worrydream.com/refs/Hamming_1997_-_The_Art_of_Doing_Science_and_Engineering.pdf); Willison's 'edit out the made-up rationale' rule (https://simonwillison.net/tags/llms/)

#### 6. Vary the rhythm; LLMs can't (yet)

**Mechanism**: Peer-grade evidence: LLM prose has measurably narrower sentence-length variance and repeats syntactic templates. Human countermeasure: deliberately mix a 3-word sentence next to a 28-word sentence; cut every third 'and' to a period; let one paragraph be a single line. Read aloud — if every sentence has the same cadence, rewrite at least one to break the pattern.

**Source**: arXiv 2509.19163 'Measuring AI Slop in Text' — POS template repetition + narrow length variance (https://arxiv.org/html/2509.19163v2); Charlie Guo's Field Guide: 'Sentences are roughly the same length. Paragraphs follow the same rhythm.' (https://www.ignorance.ai/p/the-field-guide-to-ai-slop)

#### 7. Voice is first-person plural in tutorials, second-person imperative in how-tos, voiceless in reference

**Mechanism**: Match the pronoun to the mode. Tutorial = 'We capture the checkpoint, then restore it.' How-to = 'Run `bene checkpoint <id>`. Verify with `bene ls`.' Reference = no pronouns: 'Returns a CheckpointId. Raises AgentNotFound if the agent does not exist.' BENE's docs/checkpoints.md drifts between all three. Pick one per page or per H2.

**Source**: Diátaxis tutorials: 'We … In this tutorial, we will …' (https://diataxis.fr/tutorials/); Diátaxis reference: 'State facts about the machinery' (https://diataxis.fr/reference/)

#### 8. No invented rationale; cite the mechanism or stay silent

**Mechanism**: Willison's specific rule: an LLM will add 'This is designed to help make code easier to maintain' because it sounds reasonable — strip it. Replace 'designed to' / 'helps you' / 'enables' / 'empowers' with the actual mechanism ('writes blob pointers, not file copies, so take them freely' — this is mechanism, not pitch). If you can't state the mechanism, the sentence is decoration; cut it.

**Source**: Simon Willison on editing LLM-generated docs: 'edit it to ensure it doesn't express opinions or say things like ''This is designed to help make code easier to maintain'' — that's an expression of a rationale that the LLM just made up.' (https://simonwillison.net/tags/llms/)

### Applied to BENE docs

- **Problem**: Landing-page / doc-page reductive bumper-stickers like 'harness is one SQLite file' or 'a single shared, full-text-searchable memory for the whole project' — the user explicitly rejected these. They're capability-claims with no reader model and no constraint.
  - Principle: Constraint-first, not capability-first + Audience-first (who, doing what, next 60s)
  - Suggestion: Replace 'a single shared, full-text-searchable memory for the whole project' with a reader-anchored constraint: 'MemoryStore is one SQLite FTS5 table. It does not embed, does not vectorize, does not call out to any service. If you need semantic search across a million entries, use a vector store; if you need any agent to grep the last 10k findings written by any earlier agent, this is it.' Names the reader, names the limit, names when to leave.
- **Problem**: Mode-mixing on a single page. docs/checkpoints.md does explanation ('undo for agents'), tutorial (the try/except snippet), how-to (the CLI block), AND reference (what each diff reports) — under no labels. The reader doesn't know whether to copy or to study.
  - Principle: Diátaxis split — one voice per mode, never mixed on a page
  - Suggestion: Top of checkpoints.md: a 4-line H2 menu — 'I want to save state right now → How-to. I want to understand when to checkpoint → Explanation. I want the full API → Reference. I'm new and want to walk through it once → Tutorial.' Then split the page (or visibly label H2 sections by mode). The 'habit worth building: snapshot, attempt, roll back on failure' line is explanation and should not sit inside what is otherwise a how-to.
- **Problem**: Sentences that are surprise-empty filler — e.g. CLAUDE.md and the landing carry 'BENE is a local-first multi-agent orchestration framework (v0.2.0) modeled on the Sisterhood'. The reader already assumed local-first the moment they cloned a SQLite-backed repo; 'modeled on the Sisterhood' is lore that hides the actual claim (cross-session trace inheritance).
  - Principle: Information = surprise (Hamming): delete sentences whose content the reader could have written themselves
  - Suggestion: Cut the framing sentence. Open with the surprise: 'The next agent you spawn can grep every line every earlier agent ran, restore any prior agent's filesystem in one SQL statement, and refuse to promote a strategy that fails its hash-locked probe. One SQLite file, no daemon.' Each clause carries a non-obvious load. Lore stays — but moved to philosophy.md, where lore is the point.
- **Problem**: Likely scattered AI-tell phrases in 25+ markdown files (the in-progress task list confirms 'survey slop scope: docs/*.md'). Probable hits: 'robust', 'seamlessly', 'enables', 'designed to', 'leverages', 'cutting-edge', and 'It's not X. It's Y.' contrast structures inherited from earlier drafts.
  - Principle: Vary rhythm + no invented rationale (Willison) + banned-lexicon discipline (Ozigi)
  - Suggestion: Add `scripts/grep_slop.sh` running the Ozigi lexicon against `docs/**/*.md` + `site/**/*.html` + the two i18n dicts (EN + zh). Block deploy on any match. For the contrast-structure pattern (the bene landing has variants like 'not a feature list, a reader model') — keep at most one per page. Replace 'enables you to checkpoint agents' with 'checkpoints an agent' (verb, not enablement).
- **Problem**: Code blocks not load-bearing. memory.md's opening snippet is 25 lines of decorated example with comments like '# Any agent writes a result' — readable, but the prose around it repeats what the code already says. Prose is restating, not adding.
  - Principle: Code is load-bearing; prose is scaffolding (Stripe + Tailwind)
  - Suggestion: Cut the wrapping prose to one line per code block, naming purpose or a gotcha: above the write() call → 'One row, content + type + agent_id; the `key` makes it idempotent for the same agent.' Above the search() call → 'FTS5 BM25 ranking; the query string is passed straight through, so phrase-quoting and `NOT` work.' Delete sentences like 'Any agent writes a result' inside the code AND restated in prose.

### Red flags to catch

- **Words on the banned lexicon: delve, tapestry, robust, seamlessly, leverage, empower, enable, harness (as verb), unlock, supercharge, cutting-edge, game-changer, thought leadership, in today's fast-paced, at its core, plays a significant role**
  - Why bad: These are 2024-26 LLM-prose fingerprints. They survive surface edits and still trigger reader's slop-detector subroutine (Willison) and production lexicon filters (Ozigi). They also carry no mechanism — they sell instead of describing.
  - Fix: Grep the entire docs/ tree + i18n dicts. For each hit: replace with the concrete verb the word was hiding ('enable users to checkpoint' → 'checkpoint'; 'leverage SQLite' → 'is one SQLite file'; 'robust orchestration' → name the property: 'survives kill -9 mid-run because state is fsynced per turn').
- **Contrast structure: 'It's not X. It's Y.' / 'Not a feature list — a reader model.' / 'This isn't a library. It's a harness.'**
  - Why bad: LLMs reflexively reach for this pattern; humans use it once for emphasis, models use it every third paragraph. Charlie Guo and Ozigi both flag this as a top-3 tell. Worse, it reads as marketing-pitch rhythm, which makes a dev-tool doc feel untrustworthy.
  - Fix: Allow at most one per page, and only when the X-claim is a real claim made by someone else (e.g., a competitor's docs, a misreading you're correcting). Otherwise rewrite as the positive assertion alone: instead of 'Not a feature list — a reader model', just 'Here is what you can do in 60 seconds: …'.
- **Em-dash as default punctuation (more than ~2 per ~500 words), or '— ' between every noun phrase**
  - Why bad: Em-dash density is one of the most cited 2025 tells (Charlie Guo, Decrypt, arXiv 2509.19163). Few humans write with em-dashes at that rate; the rhythm becomes uniform.
  - Fix: Per page: count em-dashes, target ≤ 3 (excluding code). Replace with: period (start a new short sentence), comma (subordinate clause), colon (definition), or parenthesis (aside). The remaining em-dashes should mark a genuine interruption of thought, not a rhythm choice.
- **Sentence-length monotony — three sentences in a row all 18-24 words, no 1-line punch sentence in the paragraph**
  - Why bad: arXiv 2509.19163 measures this directly: LLM prose has narrower length variance. The reader feels it as 'too smooth', even if they can't articulate why. Stripe and Tailwind both use punch sentences ('You can work on only one object per request.' / 'The opposite of a feature.') to break rhythm.
  - Fix: After draft, for every paragraph of >3 sentences, force one sentence to be ≤6 words or ≥30 words. Read aloud; if the cadence is even, break it.
- **Invented rationale verbs: 'designed to', 'aims to', 'helps you', 'makes it easy to', 'so that you can'**
  - Why bad: Willison's specific catch: the model invents a reason because reasons sound good. None of these state a mechanism. The reader cannot verify them. They are pure surface.
  - Fix: For each hit, demand: what is the mechanism? Replace 'designed to help you restore quickly' with the mechanism: 'restore is one SQL UPDATE; it returns when the rows commit'. If you cannot state the mechanism, the sentence is decoration — delete it.
- **Affirmation-tells / assistant-voice openers: 'Certainly!', 'Here is', 'Let's explore', 'In this guide, we'll walk through', 'Welcome to the documentation!'**
  - Why bad: These are direct artifacts of chat-instruction-tuned models (Ozigi's Gemini affirmation tells). Postgres docs open with 'Chapter 1. Getting Started'. Stripe docs open with the first useful sentence. Welcome-banners are slop.
  - Fix: Delete the opener. Start with the first useful sentence — almost always one that names a constraint, a code block, or a reader action. Postgres model: title + content, no preamble.
- **Bullet-list explosion: every section has a 4-7-item bulleted list, even where prose or a table would be clearer; bullets are not parallel (different lengths, different verb forms)**
  - Why bad: LLMs default to bullets for any list-shaped thought; humans reach for tables, sentences, or a single paragraph. Non-parallel bullets are the specific tell (e.g., the BENE memory.md type table is fine — parallel, scannable — but a bullet list of 6 'benefits' isn't).
  - Fix: Per page: count bulleted lists. If > 3, convert at least one to (a) a prose paragraph, (b) a table (parallel attributes), or (c) a code block (if it's really a sequence of commands). Bullets only when items are genuinely peer-level and unordered.
- **Closing recap or 'big picture' summary paragraph at the bottom of every page**
  - Why bad: Five-paragraph-essay residue. Charlie Guo flags 'conclusions zoom out to a vague bigger picture no one asked for.' Stripe and Postgres reference pages just stop when the API list ends.
  - Fix: End on the last useful sentence — usually a 'see also' link, a known gotcha, or just the last code block. Delete any closing paragraph that contains 'ultimately', 'in summary', 'as we've seen', 'this empowers you to…'.
- **Bold-colon paragraph prefix used as section structure: '**Snapshot:** description. **Restore:** description. **Diff:** description.'**
  - Why bad: Ozigi explicitly lists this as a structural AI tell. It's a model's way of imposing visible hierarchy without committing to a real heading. Human writers either use real H3 headings or write a single prose sentence.
  - Fix: Either promote to real H3 (### Snapshot) or rewrite as prose ('You snapshot before risky work; you restore on failure; you diff to see what the run changed.'). Bold-colon prefix is banned at lint level.

---
