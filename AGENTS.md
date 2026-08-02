# AGENTS.md — bene

## Droid skills (global)

Droid sessions in this repo can load the following skills from `~/.factory/skills/`.
Activate by skill name when the task matches the trigger.

| Skill | Use when | Trigger keywords |
|---|---|---|
| `ai-scientist` | AI-Scientist-v2 research workflows, BFTS experiments, paper/review stages, run ledgers | ai-scientist, BFTS, experiment, novelty, paper, writeup |
| `bene` | Multi-agent harness, engrams, probes, kill gates, BENE CLI/MCP, fleet meta-harness | bene, engram, probe, kill gate, mh search, autonomy ladder |
| `fleet-doctor` | Fleet stall/restart/OOM recovery, session/daemon revival, health checks | fleet-doctor, revive fleet, fleet health, bootstrap fleet, self-heal |
| `fleet-enroll` | Fleet enrollment, A2A bus registration, sweep watch, fleet comms, COLLAB_CAPSULE | fleet-enroll, enroll, A2A, collab capsule, watch coverage |
| `mroute` | Service-facing task routing, dispatch worker selection, cross-lineage handoff | mroute, route task, dispatch worker, fleet router, cross-lineage |
| `orch-proj` | Long-running project orchestration, milestones, evidence gates, subagent delegation | orch-proj, milestone, fleet-goal, collab capsule, delegate, long-term project |
| `prisma_deep_plan` | Deep planning, architecture decisions, debugging, reviews via the Prisma planner | prisma deep plan, deep planning, architecture review, refactoring plan |
| `weco` | Code optimization against measurable metrics (speed, accuracy, cost, memory) | weco, optimize, make it faster, reduce latency, lower cost |

Skill files live under `~/.factory/skills/<skill>/SKILL.md`. For runtimes without a
native skill loader, read the relevant SKILL.md into context.
