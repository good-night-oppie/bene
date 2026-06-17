#!/usr/bin/env bash
# Produce a flat MANIFEST.txt of release artifacts (Oppie Released-Builds parallel).
# Format: <sha256>  <size>  <relpath>
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
ART_DIR="${ART_DIR:-$REPO_ROOT/artifacts}"
DIST_DIR="${DIST_DIR:-$REPO_ROOT/dist}"
MANIFEST="$ART_DIR/MANIFEST.txt"

mkdir -p "$ART_DIR"

TAG="${GITHUB_REF_NAME:-$(git -C "$REPO_ROOT" describe --tags --exact-match 2>/dev/null || echo untagged)}"
COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
{
  echo "# bene release manifest"
  echo "# tag=$TAG"
  echo "# commit=$COMMIT"
  echo "# ts=$TS"
  echo "# format: <sha256>  <size>  <relpath>"
  for d in "$DIST_DIR" "$ART_DIR"; do
    [[ -d "$d" ]] || continue
    while IFS= read -r -d '' f; do
      [[ "$f" == "$MANIFEST" ]] && continue
      [[ "$f" == "$MANIFEST.sha256" ]] && continue
      sha="$(sha256sum "$f" | awk '{print $1}')"
      size="$(stat -c %s "$f")"
      rel="${f#"$REPO_ROOT"/}"
      printf '%s  %s  %s\n' "$sha" "$size" "$rel"
    done < <(find "$d" -maxdepth 3 -type f -print0 | sort -z)
  done
} > "$TMP"
mv "$TMP" "$MANIFEST"

sha256sum "$MANIFEST" | awk '{print $1}' > "$MANIFEST.sha256"
echo "ok: $MANIFEST ($(wc -l < "$MANIFEST") lines)"
