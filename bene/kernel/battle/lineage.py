"""SharedLog lineage writer for battle harness evolution — Lane B / B4.

Writes a type='evolution' entry to the fleet A2A bus (a2a-coord.db) so
every lineage session can trace the run.  Falls back silently when the bus
database is unreachable (evolution still runs; lineage is best-effort).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BUS = "/home/admin/gh/bene-main/a2a-coord.db"


def write_lineage(
    run_id: str,
    payload: dict[str, Any],
    bus_path: str = _DEFAULT_BUS,
) -> int | None:
    """Append a lineage entry to the fleet SharedLog bus.

    Returns the inserted log_id on success, None on failure (non-fatal).
    """
    try:
        con = sqlite3.connect(bus_path)
        c = con.cursor()
        c.execute("SELECT MAX(position) FROM shared_log")
        row = c.fetchone()
        max_pos = row[0] if row and row[0] is not None else 0
        # shared_log type CHECK only allows ('intent','vote','decision','commit','result',
        # 'abort','policy','mail') — 'evolution' is rejected on a real bene db. Use the
        # allowed 'result' type + carry the evolution marker in the payload (PR #64 review).
        #
        # ref_id is `INTEGER REFERENCES shared_log(log_id)` (bene/schema.py): a thread/reply
        # link to another row's log_id, NOT a free-form id slot. The ULID run_id is not a
        # log_id, so it must NOT go there — it makes the row malformed for ref/thread readers,
        # an FK-enabled writer would reject it, and it pollutes idx_shared_log_ref. Keep the
        # run id in the payload and write ref_id=NULL (no row to thread to). (PR #66 review)
        marked = {"kind": "evolution", "run_id": run_id, **payload}
        c.execute(
            "INSERT INTO shared_log (position, type, agent_id, ref_id, payload) VALUES (?,?,?,?,?)",
            (max_pos + 1, "result", "bene-core", None, json.dumps(marked)),
        )
        con.commit()
        log_id = c.lastrowid
        con.close()
        return log_id
    except Exception as exc:
        logger.warning("lineage write failed (non-fatal): %s", exc)
        return None
