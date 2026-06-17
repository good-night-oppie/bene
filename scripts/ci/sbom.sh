#!/usr/bin/env bash
# Generate a CycloneDX SBOM (Python deps only) from the uv lockfile.
# Output: artifacts/sbom.json
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/artifacts}"
OUT="$OUT_DIR/sbom.json"

mkdir -p "$OUT_DIR"

if ! uv tool list 2>/dev/null | grep -q '^cyclonedx-bom '; then
  uv tool install --quiet 'cyclonedx-bom>=4.4'
fi

REQ="$(mktemp)"
trap 'rm -f "$REQ"' EXIT
uv export --no-dev --no-emit-project --quiet > "$REQ"

uv tool run cyclonedx-bom \
  --of json \
  --output-file "$OUT" \
  --input-format requirements \
  --input-file "$REQ"

SIZE="$(stat -c %s "$OUT")"
COMPS="$(python3 -c 'import json,sys; d=json.load(open("'"$OUT"'")); print(len(d.get("components",[])))')"
echo "ok: $OUT ($SIZE bytes, $COMPS components)"
