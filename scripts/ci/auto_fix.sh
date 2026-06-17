#!/usr/bin/env bash
# Auto-fix bot: ruff fix + format. Opens a PR. Never pushes to main.
set -euo pipefail

if [ -n "${GITHUB_ACTIONS:-}" ]; then
  git config user.name "bene-autofix-bot"
  git config user.email "bene-autofix-bot@users.noreply.github.com"
fi

BRANCH="autofix/ci-${GITHUB_RUN_ID:-local}-$(date +%s)"
BASE_BRANCH="${BASE_BRANCH:-main}"

uv sync --dev --group temporal
uv run ruff check bene/ tests/ --fix --unsafe-fixes || true
uv run ruff format bene/ tests/ || true

if git diff --quiet bene/ tests/; then
  echo "no autofixes produced"
  exit 0
fi

git checkout -b "${BRANCH}"
git add bene/ tests/
git commit -m "chore(ci): auto-fix lint/format

Reported by AI agent"

if [ -n "${GITHUB_TOKEN:-}" ]; then
  git push -u origin "${BRANCH}"
  gh pr create \
    --title "chore(ci): auto-fix lint/format" \
    --body "Automated lint/format fixes from CI auto-fix bot. Reported by AI agent" \
    --base "${BASE_BRANCH}" --head "${BRANCH}" \
    --label "ai-reported" --label "autofix" || true
else
  echo "no GITHUB_TOKEN — diff stays local"
fi
