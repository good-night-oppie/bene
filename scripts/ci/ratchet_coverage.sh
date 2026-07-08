#!/usr/bin/env bash
# Ratchet .coverage-floor upward after a green main build.
#
# Policy (locked in .factory/specs/bene-cicd-redesign-tiered.md):
#   floor_init = 60                  (when file missing)
#   margin     = 1   (percentage)    keep buffer below measured to absorb flake
#   max_bump   = 5   (percentage)    cap per-merge ratchet
#   ceiling    = 98                  (above this, never fail merges over rounding)
#
# Inputs:  COVERAGE_PCT env var OR coverage.xml in cwd
# Outputs: .coverage-floor written iff value changed; exit 0 either way
#          stdout is one summary line ("ratchet: <old> -> <new>" or "ratchet: noop")
#          exit 2 only if inputs are malformed
set -euo pipefail

FLOOR_FILE="${FLOOR_FILE:-.coverage-floor}"
INIT_FLOOR="${INIT_FLOOR:-60}"
MARGIN="${MARGIN:-1}"
MAX_BUMP="${MAX_BUMP:-5}"
CEILING="${CEILING:-98}"

# Resolve measured percent.
if [[ -n "${COVERAGE_PCT:-}" ]]; then
  MEASURED="$COVERAGE_PCT"
elif [[ -f coverage.xml ]]; then
  MEASURED="$(python3 -c '
import sys, xml.etree.ElementTree as ET
r = ET.parse("coverage.xml").getroot()
rate = float(r.attrib.get("line-rate", "0"))
print(int(rate * 100))
')"
else
  echo "FATAL: provide COVERAGE_PCT env var or coverage.xml" >&2
  exit 2
fi

[[ "$MEASURED" =~ ^[0-9]+$ ]] || { echo "FATAL: measured not int: $MEASURED" >&2; exit 2; }

if [[ -f "$FLOOR_FILE" ]]; then
  CURRENT="$(cat "$FLOOR_FILE")"
  [[ "$CURRENT" =~ ^[0-9]+$ ]] || { echo "FATAL: floor not int: $CURRENT" >&2; exit 2; }
else
  CURRENT="$INIT_FLOOR"
fi

# Candidate = measured - margin, clamped to [current, current+max_bump].
CANDIDATE=$(( MEASURED - MARGIN ))
(( CANDIDATE < CURRENT ))      && CANDIDATE=$CURRENT
(( CANDIDATE > CURRENT + MAX_BUMP )) && CANDIDATE=$(( CURRENT + MAX_BUMP ))
(( CANDIDATE > CEILING ))      && CANDIDATE=$CEILING

if [[ "$CANDIDATE" == "$CURRENT" ]]; then
  echo "ratchet: noop (floor=$CURRENT, measured=$MEASURED)"
  exit 0
fi

echo "$CANDIDATE" > "$FLOOR_FILE"
echo "ratchet: $CURRENT -> $CANDIDATE (measured=$MEASURED, margin=$MARGIN, max_bump=$MAX_BUMP)"
