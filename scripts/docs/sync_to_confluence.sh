#!/usr/bin/env bash
# End-to-end Confluence sync for BENE docs.
#
# What it does, in order:
#   1. Stages markdown bodies with image/cross-ref transforms → /tmp/confluence-staged/
#   2. Pushes 16 existing sub-pages + creates 10 new pages (tutorials t00–t08, cs01)
#   3. Re-stages with new page IDs auto-merged → cross-refs to new pages now resolve
#   4. Re-pushes the pages whose cross-refs changed (idempotent — only mutated content)
#   5. Attaches all 31 demo gifs to the right pages via REST API
#
# Prereqs (one-time):
#   - pip install requests markdown
#   - export ATLASSIAN_EMAIL=you@oppie.com
#   - export ATLASSIAN_API_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens
#
# Usage:
#   ./scripts/sync_to_confluence.sh             # do it
#   ./scripts/sync_to_confluence.sh --dry-run   # preview only

set -euo pipefail
cd "$(dirname "$0")/.."

DRY=${1:-}

# Use system Python (the bene repo's .venv has no `markdown` package by default).
# Override with `PY=...` if you have a venv with markdown+requests installed.
if [[ -z "${PY:-}" ]]; then
  if [[ -x /usr/bin/python3 ]] && /usr/bin/python3 -c 'import markdown, requests' 2>/dev/null; then
    PY=/usr/bin/python3
  else
    PY=python3
  fi
fi
echo "Using interpreter: $PY ($($PY --version 2>&1))"

echo "========================================"
echo "BENE → Confluence sync"
echo "========================================"

# Sanity: env
if [[ -z "${ATLASSIAN_EMAIL:-}" || -z "${ATLASSIAN_API_TOKEN:-}" ]]; then
  echo "ERROR: set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN env vars first." >&2
  echo "  Get a token at: https://id.atlassian.com/manage-profile/security/api-tokens" >&2
  exit 2
fi

if [[ "$DRY" == "--dry-run" ]]; then
  echo
  echo "=== Stage 1: transform (dry-run preview) ==="
  $PY scripts/transform_for_confluence.py
  echo
  echo "=== Stage 2: push plan ==="
  $PY scripts/push_content_to_confluence.py --dry-run
  echo
  echo "=== Stage 3: gif-upload plan ==="
  $PY scripts/upload_gifs_to_confluence.py --dry-run
  echo
  echo "Dry-run done. Re-run without --dry-run to execute."
  exit 0
fi

echo
echo "=== Stage 1: stage markdown for Confluence ==="
$PY scripts/transform_for_confluence.py

echo
echo "=== Stage 2: first push (updates 16 + creates 10) ==="
$PY scripts/push_content_to_confluence.py

echo
echo "=== Stage 3: re-stage to pick up new page IDs ==="
$PY scripts/transform_for_confluence.py

echo
echo "=== Stage 4: re-push to fix inter-tutorial cross-refs ==="
$PY scripts/push_content_to_confluence.py

echo
echo "=== Stage 5: upload all 31 gifs as page attachments ==="
$PY scripts/upload_gifs_to_confluence.py

echo
echo "========================================"
echo "✓ Sync complete."
echo "========================================"
echo "Visit: https://oppie.atlassian.net/wiki/spaces/EN/pages/3649339396"
