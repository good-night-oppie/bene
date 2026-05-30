#!/usr/bin/env bash
# UserPromptSubmit: inject inoculation protocol + spec + scope each turn.
# Per SSC (arXiv:2507.18742) spec resident in context drops gaming 50-70% → <10%.
set -euo pipefail

REPO="${CLAUDE_PROJECT_DIR:-$PWD}"
HARNESS="$REPO/.harness"

cat >/dev/null 2>&1 || true  # consume stdin

[ -f "$HARNESS/spec.md" ] || exit 0

[ -f "$HARNESS/REWARD_HACK_PROTOCOL.md" ] && {
    cat "$HARNESS/REWARD_HACK_PROTOCOL.md"
    echo ""
}

echo "## Active spec (.harness/spec.md — top 80 lines)"
echo ""
head -n 80 "$HARNESS/spec.md"
echo ""

[ -f "$HARNESS/files-allowed" ] && {
    echo "## In-scope files (.harness/files-allowed)"
    grep -v '^\s*#' "$HARNESS/files-allowed" | grep -v '^\s*$' | head -n 40
    echo ""
}

echo "## Anti-reward-hack reminder"
echo "Stop hook runs: detectors (suppression, scope, test-vs-src, verifier), "
echo "fresh test run, test-count regression, optional heldout, LLM judge. "
echo "Disclose shortcuts via tagged ### heading in .harness/disclosure.md."
