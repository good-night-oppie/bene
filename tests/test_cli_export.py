"""`bene export` — a single-agent snapshot must actually RUN (it VACUUM-crashed:
`cannot VACUUM from within a transaction`, exit 1) and must NOT leak another
agent's rows. The delete-list was hardcoded and missed `memory`/`shared_log`;
the fix discovers agent-scoped tables dynamically + commits before VACUUM.
"""

from __future__ import annotations

import sqlite3

from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.memory import MemoryStore
from bene.shared_log import SharedLog


def _seed(db_path: str) -> tuple[str, str]:
    b = Bene(db_path)
    keep = b.spawn("keep")
    drop = b.spawn("drop")
    mem = MemoryStore(b.conn)
    log = SharedLog(b.conn)
    for aid in (keep, drop):
        b.write(aid, "/note.txt", aid.encode())
        mem.write(aid, f"memory of {aid}", type="insight", key="k")
        log.mail(aid, keep, f"hi from {aid}")
    b.close()
    return keep, drop


def test_export_runs_without_vacuum_crash_and_isolates_one_agent(tmp_path):
    db = str(tmp_path / "multi.db")
    keep, drop = _seed(db)
    out = str(tmp_path / "snap.db")

    res = CliRunner().invoke(cli, ["export", keep, "-o", out, "--db", db])
    assert res.exit_code == 0, res.output  # regression: used to crash in VACUUM

    conn = sqlite3.connect(out)
    try:
        # The snapshot keeps only the target agent across EVERY agent-scoped table,
        # including memory/shared_log that the old hardcoded list silently leaked.
        for table in ("agents", "files", "memory", "shared_log"):
            ids = {r[0] for r in conn.execute(f"SELECT agent_id FROM {table}")}
            assert drop not in ids, f"{table} leaked the other agent"
            if table != "agents":
                assert keep in ids, f"{table} dropped the target agent's rows"
        # the memory FTS shadow stayed in sync via its AFTER DELETE trigger
        fts_ids = {r[0] for r in conn.execute("SELECT agent_id FROM memory_fts")}
        assert drop not in fts_ids and keep in fts_ids
    finally:
        conn.close()
