"""Debt sweeper — continuous GC for agent-generated slop (OpenAI HE pt 7).

Manual cleanup cannot keep pace with agent throughput; encode taste as
machine-checkable signatures and sweep on a schedule. Findings land as a
``report`` engram so the debt curve is itself queryable history.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bene.kernel.engrams import EngramStore

SIGNATURES: dict[str, re.Pattern] = {
    "debug_print": re.compile(
        r"^\s*(print\(['\"]?(DEBUG|XXX|HERE|TEMP)|console\.log\(|debugger\b|breakpoint\(\))",
        re.IGNORECASE,
    ),
    "stale_todo": re.compile(r"#\s*(TODO|FIXME|HACK)\b(?!\s*\(\w+\))", re.IGNORECASE),
    "dead_import": re.compile(r"^\s*import\s+pdb\b|^\s*from\s+pdb\s+import"),
}
DUP_WINDOW = 3  # consecutive lines considered a block for duplicate detection


@dataclass
class SweepReport:
    findings: list[dict[str, Any]] = field(default_factory=list)
    files_scanned: int = 0
    engram_id: str | None = None

    def by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f["type"]] = counts.get(f["type"], 0) + 1
        return counts


class DebtSweeper:
    def __init__(self, store: EngramStore | None = None) -> None:
        self.store = store

    def _scan_text(self, label: str, text: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        lines = text.splitlines()
        for n, line in enumerate(lines, 1):
            for sig, pattern in SIGNATURES.items():
                if pattern.search(line):
                    findings.append(
                        {"type": sig, "file": label, "line": n, "text": line.strip()[:120]}
                    )
        # duplicated blocks: identical DUP_WINDOW-line windows appearing twice
        seen: dict[str, int] = {}
        for i in range(0, max(0, len(lines) - DUP_WINDOW + 1)):
            block = "\n".join(s.strip() for s in lines[i : i + DUP_WINDOW])
            if len(block) < 40:  # ignore trivial/blank windows
                continue
            if block in seen:
                findings.append(
                    {
                        "type": "duplicated_block",
                        "file": label,
                        "line": i + 1,
                        "text": f"duplicates lines starting at {seen[block]}",
                    }
                )
                break  # one duplicate finding per file is enough signal
            seen[block] = i + 1
        return findings

    def scan_paths(self, paths: list[str]) -> SweepReport:
        report = SweepReport()
        for p in paths:
            path = Path(p)
            if not path.is_file():
                continue
            report.files_scanned += 1
            report.findings.extend(self._scan_text(str(path), path.read_text(errors="replace")))
        self._persist(report, scope=f"paths:{len(paths)}")
        return report

    def scan_agent_vfs(self, bene: Any, agent_id: str) -> SweepReport:
        """Sweep an agent's virtual filesystem (the in-db workspace)."""
        report = SweepReport()
        rows = bene.conn.execute(
            "SELECT DISTINCT path FROM files WHERE agent_id = ? AND deleted = 0 AND is_dir = 0",
            (agent_id,),
        ).fetchall()
        for (path,) in rows:
            try:
                text = bene.read(agent_id, path).decode(errors="replace")
            except Exception:  # noqa: BLE001 — unreadable/binary entries skipped
                continue
            report.files_scanned += 1
            report.findings.extend(self._scan_text(path, text))
        self._persist(report, scope=f"vfs:{agent_id}", agent_id=agent_id)
        return report

    def _persist(self, report: SweepReport, *, scope: str, agent_id: str | None = None) -> None:
        if self.store is None:
            return
        report.engram_id = self.store.append(
            "report",
            f"sweep:{scope} ({len(report.findings)} findings)",
            json.dumps({"by_type": report.by_type(), "findings": report.findings}, indent=1),
            provenance={"system": "bene.kernel.harness.sweeper"},
            agent_id=agent_id,
            metadata={"findings": len(report.findings), "files": report.files_scanned},
        )
