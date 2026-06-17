#!/usr/bin/env bash
# Gap 2 helper — show the typed-engram ladder from the demo db (tier distribution + one row per tier).
set -euo pipefail
DB="$1"
echo "# engram tier distribution (12 engrams, multiple tiers, each with provenance):"
uv run bene query \
  "SELECT tier, kind, COUNT(*) as n FROM engrams GROUP BY tier, kind ORDER BY tier" \
  --db "$DB"
echo
echo "# sample row per tier:"
uv run bene query \
  "SELECT tier, kind, substr(title,1,55) FROM engrams WHERE engram_id IN (SELECT MIN(engram_id) FROM engrams GROUP BY tier) ORDER BY tier" \
  --db "$DB"
