#!/usr/bin/env bash
# Gap 3 helper — show the 4-signal trust composite as 5 aligned lines.
set -euo pipefail
DB="$1"
AGENT=$(uv run bene --json ls --db "$DB" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["agent_id"])')
TRUST=$(uv run bene trust "$AGENT" --db "$DB")
python3 - "$TRUST" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
for k, v in d["signals"].items():
    print(f"  {k:<25} {v['value']:.2f}   {v['note']}")
print(f"  composite                 {d['composite']:.2f}   ({d['denials']} denials so far)")
PY
