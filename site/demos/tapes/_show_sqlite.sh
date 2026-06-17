#!/usr/bin/env bash
# Gap 4 helper — bene.db is plain SQLite; any tool that speaks SQLite can read it.
set -euo pipefail
DB="$1"
ls -la "$DB"
echo
python3 - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
for row in con.execute(
    "SELECT tier, kind, substr(title,1,40) FROM engrams ORDER BY tier DESC LIMIT 5"
):
    print(row)
PY
