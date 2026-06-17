#!/usr/bin/env bash
# Parse mypy output into a one-file-per-line manifest for the refactor swarm.
# Usage: ./scripts/ci/manifest_from_mypy.sh [max_files]
set -eu
set -o pipefail 2>/dev/null || true

MAX_FILES="${1:-16}"
OUT_DIR=".orchestra/refactor"
mkdir -p "${OUT_DIR}"

# Skip regeneration if caller pre-staged a manifest (e.g. manual file
# selection). Useful when retrying a swarm with a curated slim manifest.
if [ "${BENE_KEEP_MANIFEST:-0}" = "1" ] && [ -s "${OUT_DIR}/manifest.txt" ]; then
  count=$(wc -l < "${OUT_DIR}/manifest.txt" | tr -d ' ')
  echo "manifest=${OUT_DIR}/manifest.txt files=${count} (keep-existing)"
  exit 0
fi

RAW="${OUT_DIR}/mypy.raw"
MANIFEST="${OUT_DIR}/manifest.txt"
ERRORS_BY_FILE="${OUT_DIR}/errors-by-file.txt"

uv run mypy --ignore-missing-imports --no-error-summary --no-color-output \
  bene/ tests/ > "${RAW}" 2>&1 || true

# Rank by error count desc; write all candidates to a temp file first
# (avoids SIGPIPE 141 when head closes the pipe early), then filter and
# truncate to MAX_FILES via a single awk pass.
CANDIDATES=$(mktemp)
awk -F: '/^[^[:space:]]+\.py:[0-9]+: (error|note):/ { print $1 }' "${RAW}" \
  | sort | uniq -c | sort -rn | awk '{print $2}' > "${CANDIDATES}"

: > "${MANIFEST}"
kept=0
while IFS= read -r f; do
  [ "${kept}" -ge "${MAX_FILES}" ] && break
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || continue
  git diff --quiet HEAD -- "$f" >/dev/null 2>&1 || continue
  echo "$f" >> "${MANIFEST}"
  kept=$((kept + 1))
done < "${CANDIDATES}"
rm -f "${CANDIDATES}"

: > "${ERRORS_BY_FILE}"
while IFS= read -r f; do
  [ -z "${f}" ] && continue
  echo "=== ${f} ===" >> "${ERRORS_BY_FILE}"
  grep -F "${f}:" "${RAW}" >> "${ERRORS_BY_FILE}" || true
  echo "" >> "${ERRORS_BY_FILE}"
done < "${MANIFEST}"

count=$(wc -l < "${MANIFEST}" | tr -d ' ')
echo "manifest=${MANIFEST} files=${count}"
