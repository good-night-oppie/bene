#!/usr/bin/env bash
# Restore bene.db from a bronze-tier snapshot. Verifies sha256 before swap.
# Refuses if the destination DB is currently open (use --force to override).
#
# Usage: db_restore.sh [timestamp|current] [--force]
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DST="${DST:-$REPO_ROOT/bene.db}"
BRONZE="${BRONZE:-/mnt/gravytrain/triage/bronze/bene-cicd}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-5}"

EX_TEMPFAIL=75

TARGET="current"
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) TARGET="$arg" ;;
  esac
done

bronze_reachable() {
  [[ -d "$BRONZE" ]] || return 1
  local fstype
  fstype="$(timeout "$PROBE_TIMEOUT" stat -f -c '%T' "$BRONZE" 2>/dev/null)" || return 1
  case "$fstype" in nfs|nfs4) ;; *) return 1 ;; esac
  return 0
}

if ! bronze_reachable; then
  echo "SKIP: bronze tier not reachable: $BRONZE" >&2
  exit "$EX_TEMPFAIL"
fi

if [[ "$TARGET" == "current" ]]; then
  SRC="$(readlink -f "$BRONZE/bene.db.current")"
elif [[ "$TARGET" == */* || "$TARGET" == *.db ]]; then
  SRC="$TARGET"
else
  matches=( "$BRONZE/snapshots/$TARGET"*.db )
  if [[ ${#matches[@]} -eq 1 && -f "${matches[0]}" ]]; then
    SRC="${matches[0]}"
  else
    SRC="$BRONZE/snapshots/$TARGET.db"
  fi
fi

[[ -f "$SRC" ]] || { echo "FATAL: snapshot not found: $SRC" >&2; exit 2; }
[[ -f "$SRC.sha256" ]] || { echo "FATAL: checksum missing: $SRC.sha256" >&2; exit 3; }

(cd "$(dirname "$SRC")" && sha256sum -c "$(basename "$SRC").sha256") >/dev/null

if [[ $FORCE -eq 0 && -f "$DST" ]]; then
  if command -v lsof >/dev/null 2>&1; then
    if lsof -- "$DST" >/dev/null 2>&1; then
      echo "FATAL: $DST is currently open by another process; pass --force to override" >&2
      lsof -- "$DST" >&2 || true
      exit 4
    fi
  elif command -v fuser >/dev/null 2>&1; then
    if fuser "$DST" >/dev/null 2>&1; then
      echo "FATAL: $DST is currently in use; pass --force to override" >&2
      exit 4
    fi
  fi
fi

if [[ -f "$DST" ]]; then
  cp -a "$DST" "$DST.before-restore.$(date -u +%Y%m%dT%H%M%SZ)"
fi

cp "$SRC" "$DST.tmp.$$"
mv "$DST.tmp.$$" "$DST"

echo "ok: restored $DST from $SRC"
