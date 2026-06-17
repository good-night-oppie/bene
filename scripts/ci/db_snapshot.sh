#!/usr/bin/env bash
# Snapshot bene.db to gravytrain bronze tier using SQLite's online backup API.
#
# Exit codes (BSD sysexits convention):
#   0   success
#   2   source DB missing or sqlite3 failed (real error - fail the job)
#   75  EX_TEMPFAIL: bronze tier not reachable from this runner
#       (callers should treat as "skip, not fail")
#
# Filenames embed host+pid so concurrent runners never collide.
# Symlink update is atomic via mv -T over a tmp link, serialized by flock.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SRC="${SRC:-$REPO_ROOT/bene.db}"
BRONZE="${BRONZE:-/mnt/gravytrain/triage/bronze/bene-cicd}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-5}"

EX_TEMPFAIL=75

bronze_reachable() {
  [[ -d "$BRONZE" ]] || return 1
  local fstype
  fstype="$(timeout "$PROBE_TIMEOUT" stat -f -c '%T' "$BRONZE" 2>/dev/null)" || return 1
  case "$fstype" in nfs|nfs4) ;; *) return 1 ;; esac
  local probe host
  host="$(hostname -s)"
  probe="$BRONZE/.write-probe.$$.$host"
  timeout "$PROBE_TIMEOUT" touch "$probe" 2>/dev/null || return 1
  rm -f "$probe"
  return 0
}

[[ -f "$SRC" ]] || { echo "FATAL: source DB not found: $SRC" >&2; exit 2; }

if ! bronze_reachable; then
  echo "SKIP: bronze tier not reachable: $BRONZE" >&2
  exit "$EX_TEMPFAIL"
fi

HOST="$(hostname -s)"
USER_="${USER:-$(whoami)}"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
NAME="${TS}.${HOST}.$$.db"
TMP="$BRONZE/.tmp.$NAME"
DST="$BRONZE/snapshots/$NAME"
CURRENT="$BRONZE/bene.db.current"
LOG="$BRONZE/events.jsonl"
LOCK="$BRONZE/.symlink.lock"

mkdir -p "$BRONZE/snapshots"

if ! sqlite3 "$SRC" ".backup '$TMP'"; then
  echo "FATAL: sqlite3 .backup failed for $SRC" >&2
  rm -f "$TMP"
  exit 2
fi

SHA="$(sha256sum "$TMP" | awk '{print $1}')"
SIZE="$(stat -c %s "$TMP")"

mv "$TMP" "$DST"
echo "$SHA  $NAME" > "$DST.sha256"

(
  flock -w "$PROBE_TIMEOUT" 200 || { echo "WARN: could not acquire symlink lock; skipping current update" >&2; exit 0; }
  ln -sfn "snapshots/$NAME" "$CURRENT.tmp.$$"
  mv -T "$CURRENT.tmp.$$" "$CURRENT"
) 200>"$LOCK"

GIT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

printf '{"ts":"%s","sha256":"%s","size":%s,"name":"%s","src":"%s","branch":"%s","commit":"%s","host":"%s","user":"%s"}\n' \
  "$TS" "$SHA" "$SIZE" "$NAME" "$SRC" "$GIT_BRANCH" "$GIT_COMMIT" "$HOST" "$USER_" >> "$LOG"

find "$BRONZE/snapshots" -name '*.db' -mtime "+$RETENTION_DAYS" -delete 2>/dev/null || true
find "$BRONZE/snapshots" -name '*.db.sha256' -mtime "+$RETENTION_DAYS" -delete 2>/dev/null || true
find "$BRONZE" -maxdepth 1 -name '.tmp.*' -mmin +60 -delete 2>/dev/null || true

echo "ok: $DST ($SIZE bytes, sha256=${SHA:0:12}...)"
