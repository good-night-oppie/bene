# Project agent rules

## Startup mandate (D4 / IDEAL-4)
At the start of every session, before writing or editing any code, run:
bash /home/admin/gh/harness-engineering/scripts/sessionstart_corpus_query.sh harness agent kb

## Repo surface
Read AGENTS.md and CLAUDE.md first. Consult IDEAL_EXPERIENCE.md, EVAL.md, and .supergoal/STATE.md before planning.

## Additional directories you may read
- /home/admin/gh/agentdex-cli-main
- /home/admin/gh/eddie-agi-kb

## MCP servers to enable
- bene
- kaggle
- prisma_deep_plan
- serena
- supabase

## Skill overrides
- agentic-tui-design: name-only
- ai-engineer-resume: name-only
- aiops-alert-filter: name-only
- anthropic-fde-resume: name-only
- claude-fast-harness: off
- confluence-cli: off
- dig-qode: off
