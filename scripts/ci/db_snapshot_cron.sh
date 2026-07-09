#!/usr/bin/env bash
# Cron wrapper for db_snapshot.sh.
# Honors EX_TEMPFAIL (75) as "skip silently" so a host losing NFS doesn't spam.
# Real failures (>=2) still surface via stderr -> cron mail.
set +e
REPO_ROOT="${REPO_ROOT:-$HOME/gh/bene}"
BRONZE="${BRONZE:-/mnt/gravytrain/triage/bronze/bene-cicd}"
LOG_DIR="${LOG_DIR:-$HOME/.local/state/bene}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/db_snapshot_cron.log"

{
  echo "=== $(date -Iseconds) cron start host=$(hostname -s) ==="
  cd "$REPO_ROOT" || { echo "FATAL: missing $REPO_ROOT"; exit 0; }
  export REPO_ROOT BRONZE
  bash "$REPO_ROOT/scripts/db_snapshot.sh"
  rc=$?
  case $rc in
    0)  echo "=== ok ===" ;;
    75) echo "=== skipped: bronze unreachable ===" ;;
    *)  echo "=== FAIL rc=$rc ===" >&2 ;;
  esac
  echo "=== $(date -Iseconds) cron end ==="
} >> "$LOG" 2>&1
