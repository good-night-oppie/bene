# Reward-hack disclosure log

> If you (the agent) introduce any shortcut that the Stop hook will flag —
> skip markers, suppressions, test-count drops, scope drift, heavy test-vs-src
> ratio — write a dated entry below BEFORE the Stop hook runs.
>
> Disclosed shortcuts are flagged but not blocked. Hidden shortcuts → block.
> Inoculation finding (Anthropic, 2025): explicit disclosure of acceptable
> reward-hacking removes misaligned generalization.
>
> Each entry header MUST be a level-3 heading and start with one of:
> ```
> ### suppression:   for skip / xfail / noqa / type:ignore
> ### test-count:    for intentional test removal/rename
> ### scope:         for touching files outside files-allowed
> ### verifier:      for editing conftest/pyproject/workflows
> ### test-heavy:    for refactors that touch tests >> src
> ```
> (Token list above is documentation, not entries — matcher ignores it.)

---

(No entries yet. Phase 1 just started 2026-05-30.)
