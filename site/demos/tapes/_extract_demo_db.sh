#!/usr/bin/env bash
# Helper: run bene demo --no-ui and emit the demo db path to stdout.
# Used by gap-* tapes so the VHS Type strings don't need nested quotes.
set -euo pipefail
uv run bene demo --no-ui 2>&1 | grep -oE '/tmp/bene-demo-[^ ]+/story.db' | head -1
