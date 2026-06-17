#!/usr/bin/env bash
# Canary watcher for rc tags. Sleeps CANARY_HOURS (default 4), polling each
# hour for a `release-blocker` issue label on the rc tag's milestone or PRs.
#
# Exits 0 = clean (release-ready), 1 = blocker found, 75 = inputs missing.
set -euo pipefail

CANARY_HOURS="${CANARY_HOURS:-4}"
TAG="${TAG:-${GITHUB_REF_NAME:-}}"
REPO="${REPO:-${GITHUB_REPOSITORY:-}}"
POLL_INTERVAL="${POLL_INTERVAL:-3600}"

EX_TEMPFAIL=75
[[ -n "$TAG"  ]] || { echo "FATAL: TAG empty (set TAG or GITHUB_REF_NAME)" >&2; exit "$EX_TEMPFAIL"; }
[[ -n "$REPO" ]] || { echo "FATAL: REPO empty (set REPO or GITHUB_REPOSITORY)" >&2; exit "$EX_TEMPFAIL"; }
command -v gh >/dev/null || { echo "FATAL: gh CLI required" >&2; exit "$EX_TEMPFAIL"; }

end=$(( $(date +%s) + CANARY_HOURS * 3600 ))
echo "canary: tag=$TAG repo=$REPO duration=${CANARY_HOURS}h end=$(date -u -d "@$end" +%Y-%m-%dT%H:%M:%SZ)"

while [[ $(date +%s) -lt $end ]]; do
  count=$(gh issue list --repo "$REPO" --label release-blocker --search "$TAG in:title,body" --state open --json number --jq 'length' 2>/dev/null || echo 0)
  if [[ "$count" -gt 0 ]]; then
    echo "::error::release-blocker found ($count open issues mentioning $TAG)"
    gh issue list --repo "$REPO" --label release-blocker --search "$TAG in:title,body" --state open
    exit 1
  fi
  remain=$(( end - $(date +%s) ))
  echo "canary: clean so far, $((remain / 60))m remaining"
  (( remain <= 0 )) && break
  sleep "$(( POLL_INTERVAL < remain ? POLL_INTERVAL : remain ))"
done

echo "canary: clean for ${CANARY_HOURS}h, releasing"
exit 0
