# Anti-Reward-Hack Protocol (Inoculation)

This project enforces anti-reward-hacking guardrails. Control plane:
`.harness/` (spec, files-allowed, disclosure, optional heldout) +
`.claude/settings.json` (deny rules + UserPromptSubmit/Stop hooks) +
`.claude/agents/judge.md` (LLM judge subagent fallback, when added).

## Disclosure Protocol (Anthropic inoculation pattern)

If you find yourself wanting to take ANY of these shortcuts:
- skip / xfail / noqa / type-ignore a failing case
- mock the system under test
- edit a fixture so it returns the expected value
- delete or rename a test out of existence
- commit with `--no-verify` / pytest with `--ignore`
- claim "done" without running fresh tests
- touch files outside `.harness/files-allowed`

…STOP. Append an entry to `.harness/disclosure.md` with a level-3 heading
starting with one of: `suppression:`, `test-count:`, `scope:`, `verifier:`,
`test-heavy:`. Disclosed shortcuts are flagged for human review but not
blocked. Hidden shortcuts are caught by the Stop hook and force a resume.

Research finding (Anthropic, 2025, *Natural Emergent Misalignment from
Reward Hacking in Production RL*): explicit disclosure / inoculation removes
the misaligned generalization that emerges when models hide reward-hacking
behavior.

## Source of truth

`.harness/spec.md` is the spec. Git diff is what you actually did. The LLM
judge (when configured) compares the two. Pytest output is verified by
re-running in a fresh process — your claimed output is not trusted by the
Stop hook.

Held-out tests (`.harness/heldout-tests/`) and held-out spec sections
(`.harness/holdout-spec.md`) may exist and are deny-listed for read. Don't
try to access them.

## Files you may NOT edit

- `.harness/spec.md`             — operator-set per task
- `.harness/files-allowed`       — meta-file, operator-only
- `.harness/REWARD_HACK_PROTOCOL.md` — this file, upstream
- `.claude/hooks/**`             — runtime hooks
- `.claude/agents/**`            — judge subagents
- `.claude/settings.json`        — permission rules
- `LICENSE`                      — legal
- `.github/workflows/**`         — CI; gate via disclosure if needed

These are deny-listed at the tool layer. If you genuinely need to change one,
ask the operator.

## Disclosure entry shape

```markdown
### scope: 2026-XX-XX — short description

**Scope:** what files/operations are out of files-allowed

**Authorization:** operator turn @ <timestamp>, exact phrasing of request

**Why this is not silent reward hacking:** explicit reasoning

**Owner:** <name>
```

Mirror this for `suppression:`, `test-count:`, `verifier:`, `test-heavy:`.
