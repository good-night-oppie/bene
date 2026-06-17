"""Rule table — 20 deduped landing-copy patterns.

Source: harness-engineering audit wf_wq5ixmvbw, 2026-06-15. All 20 survived
adversarial 2-skeptic verify (12 BLOCK / 8 WARN). Each rule has:

- rule_id      : BENE-LINT-NNN
- name         : short slug
- severity     : "BLOCK" (exit 1) or "WARN" (report only)
- regex        : compiled at import-time
- prompt_hint  : doctrine anchor + concrete reframe direction — REPLAYED
                 VERBATIM to downstream Claude/Codex/Cursor as the fix prompt.
                 Do NOT edit to fit a violation; it is the contract.
- doctrine     : the canonical reference (Mom Test ch.N / Pressfield / Zinsser
                 / Storyworthy / Karpathy X=Y / Krug)

Regex notes: where the audit spec truncated a pattern (long alternations,
nested context windows), the surviving fragment has been completed faithfully
to the prompt_hint intent. False positives → allowlist.yaml, never relax regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    severity: str  # "BLOCK" | "WARN"
    regex: re.Pattern[str]
    prompt_hint: str
    doctrine: str


RULES: list[Rule] = [
    Rule(
        rule_id="BENE-LINT-001",
        name="x-equals-y-reductive",
        severity="BLOCK",
        regex=re.compile(
            r"(?im)^(?:[^\n]{0,200}?)\b(?:BENE|trust|autonomy|harness|agent|isolation|memory|context|engram|promotion|substrate)\s+(?:is|are)\s+(?:a|an|the|one|computed|local-first|structural|hash-locked|not)\b"
            r"|\b(?:is|are)\s+(?:\w+\s+){0,4}(?:,\s*(?:not|never)\s+|—\s*not\s+)\w+"
            r"|\b(?:one|a|1)\s+\w+\s*=\s*(?:one|a|1)\s+\w+"
            r"|\btrust\s+is\s+computed\b"
            r"|\bnot\s+declared\b"
        ),
        prompt_hint=(
            "Copula-shaped product-def or X-not-Y on hero/meta/H1-H3 collapses "
            "the 11pm scene into a tagline. Mom Test ch.1 / Pressfield Client's "
            "Disease / Zinsser ch.8 creeping nounism / Karpathy X=Y trap. "
            "Re-open on reader's pane (what were they doing 30s before they hit "
            'this page?), then earn the noun. KILL_LIST strings ("trust is '
            'computed", "not declared", "one X = one Y") = auto-block.'
        ),
        doctrine="Mom Test ch.1 / Pressfield Client's Disease / Zinsser ch.8 / Karpathy X=Y",
    ),
    Rule(
        rule_id="BENE-LINT-002",
        name="symmetric-n-of-a-kind-container",
        severity="BLOCK",
        regex=re.compile(
            r"(?im)<h[1-6][^>]*>\s*(?:one|two|three|four|five|six|seven|eight|nine|ten)\b[^<]{0,80}"
            r"(?:invariants?|pillars?|gaps?|surfaces?|primitives?|principles?|rules?|reasons?|"
            r"steps?|ways?|tenets?|axioms?|laws?|things?|points?|categories?|labels?|sections?)\b"
            # ZH body-prose: "每一个 X，都能落到一个 Y" forces 1:1 lore↔chrome
            # mapping. Not anchored to <h> because the ZH cousin of "every
            # beat maps to a verb" appears in <p> leads (caught silently
            # passing rules 002 in bene-8 baseline; harness-6 receipt).
            r"|每(?:一)?个[^\n。]{0,40}都能?(?:落到|对应|映射|落实)[^\n。]{0,30}"
            r"(?:CLI|verb|命令|API|primitive|动词|动作)"
        ),
        prompt_hint=(
            "Heading names a COUNT then body marches in lockstep N parallel "
            "items. Zinsser ch.3 Clutter: symmetry-for-symmetry is clutter. "
            "Storyworthy: AND/AND/AND defaults to monotony; BUT/THEREFORE "
            "breaks it. Drop the count from the heading, ship however many "
            "survive scrutiny — 2 strong items beat 5 lockstep ones."
        ),
        doctrine="Zinsser ch.3 Clutter / Storyworthy AND-AND-AND",
    ),
    Rule(
        rule_id="BENE-LINT-003",
        name="section-lead-preamble",
        severity="WARN",
        regex=re.compile(
            r"(?ms)^#{2,3}\s+[^\n]+\n+(?:>\s*[^\n]*\n+)*"
            r"(?P<lead>(?:None of (?:these|them|this)|Neither of (?:these|them)|"
            r"These are (?:the|our|some of)|This is (?:the|our|a quick|just)|"
            r"This (?:section|chapter|table|comparison|recipe|post|page|doc|guide) (?:is|covers|walks|will|aims)|"
            r"In this (?:section|chapter|post|page|doc|guide)|"
            r"Before we (?:dive|get into|start|begin|continue)|"
            r"For (?:builders|developers|devs|engineers|teams|readers|operators)))"
        ),
        prompt_hint=(
            "Section lead retreats into apology/positioning/meta-prose/audience-"
            "labeling before the first stake. Pressfield Real Estate of First "
            "Page: any sentence between title and first stakes-on-table is "
            "theft. H2 already promised the scene — lead must extend, not "
            "re-introduce."
        ),
        doctrine="Pressfield Real Estate of First Page",
    ),
    Rule(
        rule_id="BENE-LINT-004",
        name="writer-warm-noun-jargon",
        severity="WARN",
        regex=re.compile(
            # ASCII alternation keeps \b boundaries; CJK alternation drops
            # them because Python's \b never fires between two word-chars
            # under unicode (proven empirically: `\b看板\b` misses 看板 in
            # 老看板 / 看板很重要 — the existing CJK literals here were
            # latent misses that the bene-8 baseline silently passed.
            # harness-6 receipt 2026-06-15 broadened to catch in-flow ZH).
            r"(?i)(?:\b(?:substrate|primitives?|niche|pillars?|basecamp)\b"
            r"|(?:基座|白送|工具箱拼|接管子|看板|顺序才稳|这才稳|才出场))"
        ),
        prompt_hint=(
            "Category-noun (substrate/primitive/niche/pillar/基座/看板) means "
            "something crisp in the writer's head but lands as marketing-"
            "fluff. Mom Test listen-don't-lead; Zinsser creeping nounism. "
            "User has killed these in 用户纠正 commits already — every such "
            "word is a training signal. Replace with concrete capability "
            "(what's on disk, what command they run, what they get back)."
        ),
        doctrine="Mom Test listen-don't-lead / Zinsser creeping nounism",
    ),
    Rule(
        rule_id="BENE-LINT-005",
        name="first-touch-second-touch-cta-mismatch",
        severity="BLOCK",
        regex=re.compile(r"(?si)^(?P<head>.{8000,}?)<Terminal\b"),
        prompt_hint=(
            "More than 2 section breaks before the first <Terminal>: first-"
            "touch reader hits back button before reaching the verb. Mom "
            "Test ch.3 / Pressfield ch.7 / apple-wwdc demo-as-proof. Lore/"
            "Proof/Contract belong AFTER the runnable demo. Audience first, "
            "order follows."
        ),
        doctrine="Mom Test ch.3 / Pressfield ch.7 / apple-wwdc demo-as-proof",
    ),
    Rule(
        rule_id="BENE-LINT-006",
        name="section-lead-writer-warm-noun",
        severity="BLOCK",
        regex=re.compile(
            r"(?is)<h2[^>]*>.*?</h2>\s*<p[^>]*>\s*"
            r"(?:"
            r"(?:None\s+of\s+(?:these|them|the)|Not\s+(?:all|every|just)|"
            r"In\s+this\s+section|This\s+section|Here\s+we|"
            r"We\s+(?:will|now|next)|Below[, ]|The\s+following)\b"
            r"|BENE(?:'s|’s)?\s+(?:is|job|niche|substrate|goal|mission|role|aim|approach)\b"
            r")"
        ),
        prompt_hint=(
            "First paragraph after H2 = most expensive real estate. Spent on "
            "apology / meta-prose / product-positioning = theft. H2 made "
            "promise; lead must land a concrete reader-verb scene (human + "
            "time + consequence), not defend a charge no one made, not "
            "narrate the layout below."
        ),
        doctrine="Pressfield Real Estate of First Page",
    ),
    Rule(
        rule_id="BENE-LINT-007",
        name="first-touch-vs-second-touch-reader-mismatch",
        severity="BLOCK",
        regex=re.compile(
            r"(?is)<(?:pre|code|div)[^>]*\b"
            r"(?:class\s*=\s*\"[^\"]*\b(?:terminal|shell|install|bash)\b[^\"]*\"|data-terminal)"
            r"[^>]*>"
            r"(?:(?!</(?:pre|code|div)>).){0,400}?"
            r"(?:\$\s*)?(?:curl\s+-fsSL|npm\s+(?:i|install)|pnpm\s+add|yarn\s+add|"
            r"pip\s+install|uv\s+(?:add|run|tool\s+install)|brew\s+install|cargo\s+install|go\s+install)"
            r"\b(?:(?!</(?:pre|code|div)>).){0,400}?"
            r"</(?:pre|code|div)>"
            r"(?![\s\S]{0,600}?(?:<button[^>]*(?:copy|clipboard)|onClick=[^>]*copy|data-copy=))"
        ),
        prompt_hint=(
            "Install command in terminal block has no adjacent copy button "
            "— first-touch verb starved. Mom Test ch.3 + Pressfield ch.7. "
            "The first-touch reader's hand is on copy; agent-plumbing CTAs "
            "(curl SKILL.md, llms.txt) are for visit-2."
        ),
        doctrine="Mom Test ch.3 / Pressfield ch.7",
    ),
    Rule(
        rule_id="BENE-LINT-008",
        name="visual-symmetry-defeats-doctrine-hierarchy",
        severity="BLOCK",
        regex=re.compile(
            r"(?si)<(?P<tag>blockquote|div|aside|p|section)\b[^>]*"
            r"\bclass\s*=\s*[\"'][^\"']*"
            r"(?:font-mono[^\"']*border-l-\d|border-l-\d[^\"']*font-mono|"
            r"\bKicker\b|accent-bar|\baccent\b[^\"']*\bbar\b)"
            r"[^\"']*[\"'][^>]*>(?P<body>.*?)</(?P=tag)>"
        ),
        prompt_hint=(
            "N>=3 closers share identical chrome (font-mono+border-l, "
            "Kicker, accent-bar) but only a subset carry a runnable verb. "
            "Zinsser ch.7: emphasis is finite budget — reserve for load-"
            "bearing. Symmetric styling camouflages action-carriers. Give "
            "them their own visual rank or demote garnish to body prose."
        ),
        doctrine="Zinsser ch.7 emphasis is finite",
    ),
    Rule(
        rule_id="BENE-LINT-009",
        name="section-lead-apology-or-positioning",
        severity="BLOCK",
        regex=re.compile(
            r"<h2\b[^>]*>[^<]{0,200}</h2>\s*"
            r"(?:<(?:div|section|figure|small|em|strong|span)\b[^>]*>\s*)*"
            r"<p\b[^>]*>\s*"
            r"(?:"
            r"(?:None of (?:these|this|them|those|the (?:above|following))|"
            r"[A-Z][A-Za-z0-9]{1,30}(?:’|'|&rsquo;|&#8217;)s?\s+"
            r"(?:job|niche|role|aim|goal|focus|mission|purpose)\s+is\b|"
            r"what\s+(?:the\s+moment|you(?:’|')?ll\s+find|follows|"
            r"each\s+(?:row|card|column|tile))\s+(?:looks?\s+like|below|next|is)|"
            r"the\s+(?:table|section|list|diagram)\s+below)"
            # ZH section-lead defense within first 200 chars of <p>: the
            # lead narrates layout/ordering instead of dropping the reader
            # into the scene the H2 promised. Triggers are body-prose so
            # they may appear after a noun phrase, hence the [^<]{0,200}
            # prefix rather than the anchor-at-<p>-start English forms.
            r"|[^<]{0,200}(?:这个?顺序才稳"
            r"|放在[^<\n]{0,40}后面才出场"
            r"|放(?:在|到)[^<\n]{0,40}之后才(?:出场|登场|揭开|揭面)"
            r"|先[^<\n]{0,30}再讲"
            r"|留到最后才"
            r"|顺序更稳"
            r"|先后顺序)"
            r")"
        ),
        prompt_hint=(
            "Apology + positioning + layout-narration all theft from H2-paid "
            "attention. Pressfield Real Estate; Storyworthy Five-Second "
            "Moment. Plant the elephant — timestamp, verdict, cost — in the "
            "opening beat, not framing."
        ),
        doctrine="Pressfield Real Estate / Storyworthy Five-Second Moment",
    ),
    Rule(
        rule_id="BENE-LINT-010",
        name="x-equals-y-reductive-recidivism",
        severity="BLOCK",
        regex=re.compile(
            r"(?m)"
            r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)?\s+is\s+"
            r"(?:a|an|the)\s+[a-z][^.\n]{0,120}[.\n]"
            r"|\b[A-Z][A-Za-z0-9]+\s+is\s+[^.\n,]{1,60},\s*"
            r"(?:not|never)\s+[^.\n]{1,60}[.\n]"
            r"|(?i:\btrust\s+is\s+computed,\s*(?:not|never)\s+declared\b)"
            r"|\b[A-Z][A-Za-z0-9]+\s+is\s+one\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,3}[.\n]"
        ),
        prompt_hint=(
            "X=Y recidivism is fractal — flagged 9x, migrates across "
            "surfaces. Surface-fixing one line is not the fix — re-ground "
            "in what the operator did, what the system refused, what "
            "shipped. Verbs over copulas. Specific scene over category."
        ),
        doctrine="Karpathy X=Y trap (recidivism class)",
    ),
    Rule(
        rule_id="BENE-LINT-011",
        name="section-lead-writer-warm-noun-mode",
        severity="WARN",
        regex=re.compile(
            r"(?m)^#{2,4}\s+[^\n]+\n+(?:>[^\n]*\n+)?"
            r"(?:None of (?:these|this) is a knock\b"
            r"|In this section\b"
            r"|As you(?:'|’)ll see\b"
            r"|The (?:table|section|list|diagram) below\b"
            r"|What (?:the moment|this) looks like\b"
            r"|BENE(?:'|’)s (?:job|niche|role|mission|purpose|aim|goal) (?:is|are)\b"
            r"|(?:Our|This)\s+(?:product|tool|library|framework)(?:'|’)s\s+"
            r"(?:job|niche|role)\s+is\b)"
        ),
        prompt_hint=(
            "H2 made a promise; first paragraph must extend, not retreat. "
            "Pressfield Start in the Middle. Open with the smallest "
            "concrete thing the reader can DO or DECIDE next."
        ),
        doctrine="Pressfield Start in the Middle",
    ),
    Rule(
        rule_id="BENE-LINT-012",
        name="killed-word-resurrection",
        severity="WARN",
        regex=re.compile(
            r"(?i)\b(pillars?|computed,?\s+(?:not|never)\s+declared|"
            r"flattening\s+concepts?\s+to\s+one\s+SQLite|"
            r"都真实跑过|看板|接管子)\b"
        ),
        prompt_hint=(
            "User-killed token has resurrected. Highest-signal recidivism "
            "marker in repo history. Not a style nit — go back to the kill "
            "commit, re-read why it was killed (what was flattened, what "
            "compliment cost nothing), reframe around the actual artifact. "
            "Do NOT search-and-replace."
        ),
        doctrine="repo recidivism marker",
    ),
    Rule(
        rule_id="BENE-LINT-013",
        name="first-touch-vs-second-touch-cta-mismatch-nav",
        severity="BLOCK",
        regex=re.compile(
            r"(?is)(?:<(?:button|a)\b[^>]*>"
            r"[^<]*(?:\bcurl\s+[\w./:-]"
            r"|hand\s+(?:bene\s+)?to\s+your\s+agent"
            r"|paste\s+into\s+your\s+agent"
            r"|wire\s+(?:it|bene)\s+into"
            r"|integrate\s+(?:with|into)\s+your\s+(?:agent|harness)"
            r"|add\s+to\s+your\s+(?:agent|context|skill))[^<]*</(?:button|a)>"
            r"|<(?:button|a)\b[^>]*>\s*"
            r"(?:Lore|Proof|Contract|Recipes|Limits|Gap|Integrates)\s*</(?:button|a)>)"
        ),
        prompt_hint=(
            "Hero CTA / top-nav uses 2nd-touch verb or project-jargon — "
            "stranger has no copy-install-run affordance. Mom Test ch.3 + "
            "Pressfield Book Two + Krug billboard rule. First-touch verb "
            "(Copy/Install/Try/Run) gets the loudest button."
        ),
        doctrine="Mom Test ch.3 / Pressfield Book Two / Krug billboard rule",
    ),
    Rule(
        rule_id="BENE-LINT-014",
        name="hero-cta-serves-agent-not-first-touch-human",
        severity="WARN",
        regex=re.compile(
            r"(?is)<(?:Hero|section)\b[^>]*"
            r"(?:class|className)=[\"'][^\"']*"
            r"(?:\bhero\b|\bpt-(?:16|20|24|28|32)\b)"
            r"[^\"']*[\"'][^>]*>"
            r"(?:(?!</(?:Hero|section)>).)*?"
            r"(?:>\s*(?:Copy\s+(?:the\s+)?(?:llms\.txt|SKILL\.md|AGENTS\.md|mcp\.json)"
            r"|(?:SKILL|AGENTS|llms|mcp)\.(?:md|txt|json)\s*(?:↗|→)?"
            r"|(?:hand|give|paste)[^<]{0,40}(?:to|into)\s+(?:your\s+)?agent"
            r"|for\s+your\s+agent"
            r"|agent[’']?s?\s+context)[^<]*<)"
        ),
        prompt_hint=(
            "Hero hands reader to an agent before the install/run verb. "
            "11pm human's hand is on Terminal, not agent context window. "
            "Mom Test listen-don't-lead. Move agent-handoff CTA below fold "
            "or into 'For agents' section."
        ),
        doctrine="Mom Test listen-don't-lead",
    ),
    Rule(
        rule_id="BENE-LINT-015",
        name="install-terminal-without-copy-button",
        severity="WARN",
        regex=re.compile(
            r"(?is)<(Terminal|pre|code|CodeBlock|Snippet)\b"
            r"(?P<attrs>(?:(?!>).)*)>"
            r"(?P<body>(?:(?!</(?:Terminal|pre|code|CodeBlock|Snippet)>).)*?"
            r"\b(?:uv|pip|pipx|npm|pnpm|yarn|bun|brew|cargo|go\s+install|curl\s+[^\n<]*\|\s*sh)"
            r"\s+(?:add|install|run|init|i)\b"
            r"(?:(?!</(?:Terminal|pre|code|CodeBlock|Snippet)>).)*?)"
            r"</(?:Terminal|pre|code|CodeBlock|Snippet)>"
            r"(?![\s\S]{0,400}?(?:copyText\s*=|data-(?:copy|clipboard-target)|"
            r"<button[^>]*(?:copy|clipboard)))"
        ),
        prompt_hint=(
            "Install snippet missing copy affordance within 400 chars. "
            "Mom Test rule: CTA matches the action reader's hand is "
            "already reaching for. Don't add a button to silence linter — "
            "anchor the copy verb to the closest interactive element."
        ),
        doctrine="Mom Test CTA-matches-hand",
    ),
    Rule(
        rule_id="BENE-LINT-016",
        name="nav-doctrine-jargon-labels",
        severity="WARN",
        regex=re.compile(
            r"(?is)<(?:nav|header)\b[^>]*>.*?"
            r"(?:(?:label\s*[:=]\s*['\"`][^'\"`]*"
            r"\b(?:Lore|Gap|Contract|Proof|Recipes|Arch|Limits|Integrates|"
            r"Doctrine|Canon|Manifest|Ethos|Praxis)\b"
            r"[^'\"`]*['\"`])[\s\S]*?){2,}.*?</(?:nav|header)>"
        ),
        prompt_hint=(
            "Nav has >=2 doctrine-jargon labels — first-touch reader cannot "
            "decode writer-vocabulary before reading the body. Krug "
            "billboard rule: <3s scannable. Doctrine names belong on H2 "
            "anchors inside body."
        ),
        doctrine="Krug billboard rule",
    ),
    Rule(
        rule_id="BENE-LINT-017",
        name="agent-handoff-microcopy-before-human-verb",
        severity="WARN",
        regex=re.compile(
            r"(?i)\b(your|the)\s+agent\b"
            r"|\bagent[-\s]?(context|readable|window)\b"
            r"|\bpaste\s+(this|it|into)\s+(your|the)?\s*agent\b"
            r"|\bhand\s+\w+\s+to\s+your\s+agent\b"
            r"|\bdrop\s+this\s+into\s+your\s+agent\b"
        ),
        prompt_hint=(
            "Agent-pronoun microcopy in hero/CTA scope before any human-verb "
            "CTA — recasts 11pm reader as context-window curator. Mom Test "
            "+ Pressfield scene-break. Agent-handoff lives under labeled "
            "'For agents:' sub-section."
        ),
        doctrine="Mom Test / Pressfield scene-break",
    ),
    Rule(
        rule_id="BENE-LINT-018",
        name="second-touch-surface-leaks-into-first-touch-section",
        severity="WARN",
        regex=re.compile(
            r"(?is)<(?:header|nav|section[^>]*\bclass=[\"'][^\"']*\bhero\b)[^>]*>"
            r"(?:(?!</(?:header|nav|section)>).){0,4000}?"
            r"(?:href|src|data-(?:copy|url|href))=[\"'][^\"']*"
            r"\b(?:SKILL\.md|llms\.txt|mcp\.json|AGENTS\.md|\.well-known/agent)\b"
        ),
        prompt_hint=(
            "Second-touch agent-integration resource referenced in hero/top-"
            "nav. Mom Test ch.2: don't ask integration question before "
            "install. Demote to 'Agent integration' sub-section under "
            "Architecture/Docs."
        ),
        doctrine="Mom Test ch.2",
    ),
    Rule(
        rule_id="BENE-LINT-019",
        name="x-equals-y-reductive-template-cn",
        severity="WARN",
        regex=re.compile(
            r"(?im)\b(?:is|are|=)\s+(?:a|an|one|the)?\s*[\w\-]+"
            r"(?:[\w\s\-]{0,40}?),\s+not\s+[\w\-]+"
            r"|^\s*[\w一-鿿\-]{2,40}\s+(?:is|=|是)\s+"
            r"(?:a|an|one|一个|一份|一种)\s+[\w一-鿿\-]"
            # ZH "都能落到一个 Y" / "都映射到 / 成一个 Y" — the existing
            # cousin to "every beat is paired with a real CLI verb". Catches
            # the X→Y reductive template even when the subject is plural.
            r"|都能?(?:落到|映射到|映射成|对应到)\s*一个"
        ),
        prompt_hint=(
            "X=Y copula on landing surface — collapses scene into category. "
            "Mom Test ch.2 / Zinsser ch.7 creeping nounism / Karpathy X=Y. "
            "Name a verb the reader can do, an artifact they can open, or "
            "a number they can read."
        ),
        doctrine="Mom Test ch.2 / Zinsser ch.7 / Karpathy X=Y",
    ),
    Rule(
        rule_id="BENE-LINT-020",
        name="abandon-the-scene-after-landing-it",
        severity="BLOCK",
        regex=re.compile(
            r"(?ms)((?:[^.!?\n]*?"
            r"\b(?:0?\d:\d{2}|1?\d(?::\d{2})?\s*(?:am|pm|AM|PM)|midnight|"
            r"the next (?:night|morning|day)|on-call|walks?\s+(?:in|into)|"
            r"opens?\s+|finds?\s+|sees?\s+|stares?\s+|"
            r"the (?:dashboard|terminal|screen|laptop|pager|page))"
            r"[^.!?\n]*?[.!?])\s+)"
            r"((?:[A-Z][A-Z0-9_-]{2,}|[A-Z][a-zA-Z]+)\s+is\s+"
            r"(?:an?\s+|the\s+)?"
            r"(?:local-first\s+|open-source\s+|lightweight\s+|distributed\s+|"
            r"cloud-native\s+)?"
            r"(?:multi-agent|memory|context|harness|substrate|framework|"
            r"platform|library|tool|kernel|database))"
        ),
        prompt_hint=(
            "You landed a scene (timestamp/person/action) then retreated to "
            "'X is a [category]' within one beat. Storyworthy stay-in-the-"
            "five-second-moment. Pressfield Build extends Hook, doesn't "
            "zoom out. Keep the camera on the on-call's screen one more "
            "sentence."
        ),
        doctrine="Storyworthy Five-Second Moment / Pressfield Build-extends-Hook",
    ),
    Rule(
        rule_id="BENE-LINT-026",
        name="zh-gloss-density",
        severity="WARN",
        regex=re.compile(
            # Per-<p> block code-switch overload: a single <p>…</p> block that
            # re-glosses >=4 EN terms into CJK brackets 「…」. The runner does a
            # whole-file finditer, so the per-block scope is encoded in the regex
            # itself: open <p>, then 4 gloss units, each separated by a lazy body
            # that NEVER crosses a </p> — so two sub-4 blocks can't combine.
            #
            # gloss unit = a Latin token IMMEDIATELY before the bracket
            # ([A-Za-z][A-Za-z .]*「…」). FP guards baked in:
            #   (1) Latin-prefix required -> real Chinese quotation 「…」 (e.g. a
            #       Litany quote) never counts; only EN-term glosses do.
            #   (2) (?!</p>) body -> never leaks across blocks; <code>-wrapped
            #       tokens (bene.db / promote()) sit in their own element with no
            #       trailing 「…」, so they're never counted.
            #   (3) 4 units = threshold >=4 (spares dense-but-fine 0-3-pair rows).
            # zh-only by construction: EN landing has no 「…」 glosses -> 0 matches.
            r"(?is)<p\b[^>]*>"
            r"(?:(?!</p>).)*?[A-Za-z][A-Za-z .]*「[^」]*」"
            r"(?:(?!</p>).)*?[A-Za-z][A-Za-z .]*「[^」]*」"
            r"(?:(?!</p>).)*?[A-Za-z][A-Za-z .]*「[^」]*」"
            r"(?:(?!</p>).)*?[A-Za-z][A-Za-z .]*「[^」]*」"
        ),
        prompt_hint=(
            "Code-switch overload: this <p> re-glosses >=4 EN terms into 「…」 "
            "brackets in one block (offline eval「离线评测」, regression「回归"
            "问题」, pipeline「流水线」…). zh-codeswitch reads as a translator "
            "hedging every term at once — the reader is fluent enough to run "
            "the CLI, so the parenthetical CJK gloss is noise. Zinsser ch.3 "
            "Clutter. Pick the 1–2 terms a zh engineer genuinely wouldn't know, "
            "gloss those once; drop the rest to the bare EN term. Do NOT add a "
            "'never re-gloss' counter — first-use tracking is FP-heavy; just "
            "thin THIS block."
        ),
        doctrine="Zinsser ch.3 Clutter / zh code-switch density",
    ),
]


def by_id(rule_id: str) -> Rule | None:
    for r in RULES:
        if r.rule_id == rule_id:
            return r
    return None
