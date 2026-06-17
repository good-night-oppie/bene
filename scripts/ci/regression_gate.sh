#!/usr/bin/env bash
# Regression gate: compare HEAD vs base on ruff issues, coverage, test count.
#
# Mypy is intentionally NOT in this gate — typecheck advisories are a
# trivial-class signal owned by the refactor swarm. Putting them here
# would flood users with red herrings and pre-empt the swarm.
#
# When a regression is detected, the triage classifier (rule-first +
# Tier fallback) decides:
#   trivial     -> route to refactor-swarm (gate exits 0; advisory)
#   non-trivial -> hard FAIL (gate exits 1; user does advanced triage)
#
# Karpathy-style: tiny, deterministic. Uses git worktree so the working
# tree is never mutated.
set -euo pipefail

BASE_REF="${BASE_REF:-origin/main}"
ART_DIR="${RUNNER_TEMP:-/tmp}/bene-gate"
WT_DIR="${ART_DIR}/base-worktree"
mkdir -p "${ART_DIR}"

# Drive fetch from BASE_REF so PRs against non-main branches gate correctly.
BASE_BRANCH="${BASE_REF#origin/}"
git fetch origin "${BASE_BRANCH}" --depth=50 || true

cleanup() {
  git worktree remove --force "${WT_DIR}" >/dev/null 2>&1 || true
  git worktree prune >/dev/null 2>&1 || true
}
trap cleanup EXIT

git worktree prune >/dev/null 2>&1 || true

measure() {
  local label="$1"
  local workdir="$2"
  echo "==> measure ${label} in ${workdir}"
  (
    cd "${workdir}"
    uv sync --dev --group temporal >/dev/null
    uv run ruff check bene/ tests/ --output-format=json \
      > "${ART_DIR}/${label}-ruff.json" || true
    uv run pytest -q --cov=bene \
      --cov-report=json:"${ART_DIR}/${label}-cov.json" \
      --junitxml="${ART_DIR}/${label}-junit.xml" \
      || echo "tests failed on ${label} (non-fatal for gate)"
  )
}

git worktree add --detach "${WT_DIR}" "${BASE_REF}"
measure base "${WT_DIR}"
measure head "$(pwd)"

export ART_DIR
set +e
python3 scripts/ci/triage_classifier.py
verdict_rc=$?
set -e

case "$verdict_rc" in
  0)
    echo "REGRESSION GATE: trivial regression — routing to refactor swarm"
    # Mark for downstream job; gate itself does NOT block.
    echo "ROUTE_TO_REFACTOR_SWARM=true" >> "${GITHUB_ENV:-/dev/null}" || true
    exit 0
    ;;
  2)
    echo "REGRESSION GATE FAILED — non-trivial regression; user triage required"
    echo "  see ${ART_DIR}/triage.json for verdict + measurements"
    exit 1
    ;;
  3)
    echo "REGRESSION GATE OK — no regressions"
    exit 0
    ;;
  4)
    echo "REGRESSION GATE FAILED — base branch is not green (strict mode)"
    echo "  BENE_STRICT_BASE=1 set; gate refuses to compare against broken base"
    echo "  see ${ART_DIR}/triage.json for failure counts"
    exit 1
    ;;
  5)
    echo "::warning title=Base branch not green::see ${ART_DIR}/triage.json"
    echo "REGRESSION GATE OK (advisory: base is not green; comparison may be unreliable)"
    echo "  set BENE_STRICT_BASE=1 to make this a hard fail"
    exit 0
    ;;
  *)
    echo "REGRESSION GATE: triage classifier exited unexpectedly ($verdict_rc)"
    exit 1
    ;;
esac
