#!/usr/bin/env bash
# Codex UserPromptSubmit: inject IonQ anti-reward-hack protocol and active spec.
set -euo pipefail

REPO="${CODEX_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-${CURSOR_PROJECT_DIR:-}}}"
if [ -z "$REPO" ]; then
    REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
HARNESS="$REPO/.harness"

cat >/dev/null 2>&1 || true

[ -f "$HARNESS/spec.md" ] || exit 0

if [ -f "$HARNESS/REWARD_HACK_PROTOCOL.md" ]; then
    cat "$HARNESS/REWARD_HACK_PROTOCOL.md"
    echo ""
fi

echo "## Active spec (.harness/spec.md - top 80 lines)"
echo ""
head -n 80 "$HARNESS/spec.md"
echo ""

if [ -f "$HARNESS/files-allowed" ]; then
    echo "## In-scope files (.harness/files-allowed)"
    grep -v '^\s*#' "$HARNESS/files-allowed" | grep -v '^\s*$' | head -n 40
    echo ""
fi

echo "## Anti-reward-hack reminder"
echo "Codex IonQ hooks run pre-tool checks plus the Stop orchestrator."
echo "Disclose legitimate shortcuts via a tagged ### heading in .harness/disclosure.md."
