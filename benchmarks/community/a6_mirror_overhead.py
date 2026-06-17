"""PREREG row A6 — inline-hook overhead of the kernel memory mirror (Round 3).

Round-1 methodology, reproduced exactly: 1000 ``MemoryStore.write`` calls per
mode, fresh /tmp dbs, ``time.perf_counter``, single thread, two modes
(without kernel; with ``attach_kernel`` memory mirror as it ships by
default), overhead = with - without, p50 AND p95 reported; the whole
experiment runs TWICE and the LEAST favorable run governs.

Measurement honesty for Round-3 batching: the batched mirror defers row
materialisation to flush/close, so per-write latency alone would hide cost.
Both statistics are therefore reported and the LEAST favorable one is used
for the gate arithmetic:
  per_write   p50/p95 of (write_with - write_without) paired-by-rank
  amortized   (total_with_incl_close - total_without_incl_close) / N
The timed window includes ``Bene.close()`` (which drains the buffer) in BOTH
modes, so flush cost is inside the window, amortized over the N writes.

Gates (PREREG A6): absolute < 5 ms AND relative < 2x the KAOS hook overhead.
KAOS reference: Round-1 governing re-run on this host, record_outcome hook
+168.9 us/op p50 (re-run governs per protocol; not re-executed here).

Run:  uv run python benchmarks/community/a6_mirror_overhead.py
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

from bene import Bene
from bene.kernel.adapters import attach_kernel
from bene.memory import MemoryStore

N_WRITES = 1000
KAOS_HOOK_OVERHEAD_MS = 0.1689  # +168.9 us/op, Round-1 governing re-run
ABS_GATE_MS = 5.0


def _one_mode(with_kernel: bool) -> dict:
    db = str(Path(tempfile.mkdtemp(prefix=f"bene-a6-{'with' if with_kernel else 'no'}-")) / "t.db")
    b = Bene(db)
    mem = MemoryStore(b.conn)
    if with_kernel:
        attach_kernel(b, memory=mem)
    aid = b.spawn("bench")
    lat_ms = []
    t_total0 = time.perf_counter()
    for i in range(N_WRITES):
        t0 = time.perf_counter()
        mem.write(aid, f"benchmark memory body {i}", type="observation", key=f"k{i}")
        lat_ms.append((time.perf_counter() - t0) * 1000.0)
    b.close()  # drains any batched mirror rows — inside the timed window
    total_ms = (time.perf_counter() - t_total0) * 1000.0
    return {"lat_ms": lat_ms, "total_ms": total_ms}


def _run_once(run_idx: int) -> dict:
    without = _one_mode(False)
    with_k = _one_mode(True)
    p50 = statistics.median(with_k["lat_ms"]) - statistics.median(without["lat_ms"])
    p95 = (
        statistics.quantiles(with_k["lat_ms"], n=20)[18]
        - statistics.quantiles(without["lat_ms"], n=20)[18]
    )
    amortized = (with_k["total_ms"] - without["total_ms"]) / N_WRITES
    return {
        "run": run_idx,
        "p50_per_write_overhead_ms": round(p50, 4),
        "p95_per_write_overhead_ms": round(p95, 4),
        "amortized_incl_flush_ms": round(amortized, 4),
        "governing_ms": round(max(p50, amortized), 4),
    }


def main() -> int:
    runs = [_run_once(1), _run_once(2)]
    worst = max(runs, key=lambda r: r["governing_ms"])
    governing = worst["governing_ms"]
    worst_p95 = max(r["p95_per_write_overhead_ms"] for r in runs)
    rel_gate_ms = 2 * KAOS_HOOK_OVERHEAD_MS
    out = {
        "n_writes": N_WRITES,
        "runs": runs,
        "least_favorable": worst,
        "gates": {
            "absolute_lt_5ms": {
                "value_ms": max(governing, worst_p95),
                "verdict": "PASS" if max(governing, worst_p95) < ABS_GATE_MS else "LOSS",
            },
            "relative_lt_2x_kaos_hook": {
                "value_ms": governing,
                "threshold_ms": round(rel_gate_ms, 4),
                "verdict": "PASS" if governing < rel_gate_ms else "LOSS",
            },
        },
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
