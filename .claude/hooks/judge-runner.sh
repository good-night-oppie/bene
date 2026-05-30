#!/usr/bin/env bash
# Invokes the `judge` subagent in headless mode from the Stop hook.
#
# Exit semantics:
#   0 = AGREE (or judge unavailable — fail-open per Codeleash skill)
#   2 = DISAGREE — stderr carries judge rationale; Stop hook will fail(2)
#
# We use `claude -p` (headless one-shot) with explicit agent name so the
# judge runs in a fresh context isolated from the impl agent.

set -uo pipefail

REPO="${CLAUDE_PROJECT_DIR:-$PWD}"
HARNESS="$REPO/.harness"
SPEC="$HARNESS/spec.md"
JUDGE_LOG="$HARNESS/judge.log"

[ -f "$SPEC" ] || exit 0  # no spec, no judging

# Skip if claude CLI not on PATH (fail-open — don't block on missing tool)
command -v claude >/dev/null 2>&1 || {
    echo "[judge-runner] claude CLI not found, skipping" >&2
    exit 0
}

PROMPT="Read .harness/spec.md, .harness/files-allowed (if present), .harness/disclosure.md (if present). Then run \`git diff HEAD\` and emit VERDICT per your subagent instructions."

OUTPUT=$(claude -p \
    --agent judge \
    --output-format text \
    --dangerously-skip-permissions \
    "$PROMPT" 2>&1) || {
    echo "[judge-runner] claude invocation failed, fail-open" >&2
    echo "$OUTPUT" >> "$JUDGE_LOG" 2>/dev/null || true
    exit 0
}

# Append every verdict to log for telemetry
{
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    echo "$OUTPUT"
} >> "$JUDGE_LOG" 2>/dev/null || true

if echo "$OUTPUT" | grep -q "^VERDICT: DISAGREE"; then
    echo "$OUTPUT" >&2
    exit 2
fi

exit 0
