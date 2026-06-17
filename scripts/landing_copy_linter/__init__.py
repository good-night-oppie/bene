"""BENE landing-copy linter.

Source: harness-engineering wf wq5ixmvbw (68 agents / 3M tokens / 5 phases).
20 deduped rules survived adversarial 2-skeptic verify.

Hard-rail philosophy (G2 ep06): no LLM judge, regex + KILL_LIST + per-rule
allowlist. prompt_hint replayed verbatim as the fix prompt for downstream
Claude/Codex/Cursor — never editable narration.
"""
