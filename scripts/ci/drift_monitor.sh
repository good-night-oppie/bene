#!/usr/bin/env bash
# Weekly drift probe. Posts a single rolling comment on a 'drift' tracking issue.
# Signals only - never fails. Output is a markdown table.
#
# Probes:
#   - pin.env BENE_VERSION vs latest published on PyPI
#   - mypy_allowlist size (file count)
#   - coverage floor vs measured gap
#   - uv.lock age in days
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
PIN_ENV="${PIN_ENV:-$REPO_ROOT/.github/bene/pin.env}"
ALLOWLIST="${ALLOWLIST:-$REPO_ROOT/scripts/ci/mypy_allowlist.txt}"
FLOOR_FILE="${FLOOR_FILE:-$REPO_ROOT/.coverage-floor}"
LOCK="${LOCK:-$REPO_ROOT/uv.lock}"

cd "$REPO_ROOT"

# pin freshness: is the pinned PyPI version the latest published?
PIN_BEHIND="?"
if [[ -f "$PIN_ENV" ]]; then
  PIN_VER="$(grep '^BENE_VERSION=' "$PIN_ENV" | cut -d= -f2- | tr -d '"' || echo)"
  if [[ -n "$PIN_VER" ]]; then
    LATEST="$(curl -fsSL https://pypi.org/pypi/bene/json 2>/dev/null \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null || echo)"
    if [[ -n "$LATEST" ]]; then
      [[ "$PIN_VER" == "$LATEST" ]] && PIN_BEHIND="up-to-date ($PIN_VER)" || PIN_BEHIND="stale: pinned $PIN_VER, latest $LATEST"
    fi
  fi
fi

# allowlist size
ALLOW_COUNT=0
[[ -f "$ALLOWLIST" ]] && ALLOW_COUNT="$(grep -cve '^\s*$' -e '^\s*#' "$ALLOWLIST" 2>/dev/null || echo 0)"

# coverage gap
FLOOR=0
[[ -f "$FLOOR_FILE" ]] && FLOOR="$(cat "$FLOOR_FILE")"
GAP="?"
if [[ -f coverage.xml ]]; then
  MEASURED="$(python3 -c 'import xml.etree.ElementTree as ET; r=ET.parse("coverage.xml").getroot(); print(int(float(r.attrib.get("line-rate","0"))*100))')"
  GAP=$(( MEASURED - FLOOR ))
fi

# lock age
LOCK_AGE="?"
if [[ -f "$LOCK" ]]; then
  LOCK_AGE=$(( ( $(date +%s) - $(stat -c %Y "$LOCK") ) / 86400 ))
fi

cat <<EOF
# bene drift monitor

| signal              | value            | warn-if         |
|---------------------|------------------|-----------------|
| pin vs PyPI latest  | $PIN_BEHIND      | stale           |
| mypy allowlist size | $ALLOW_COUNT     | not shrinking   |
| coverage gap        | $GAP             | > 30            |
| uv.lock age (days)  | $LOCK_AGE        | > 30            |

Generated: $(date -Iseconds)
EOF
