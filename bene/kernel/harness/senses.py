"""Agent senses — a discoverability manifest generated from the live database.

OpenAI HE pt 3 (SYNTHESIS): a giant hand-maintained AGENTS.md rots and fails
("everything important = nothing important"); KAOS's own anchor docs are
hollow TODO scaffolds (GAP-AUDIT KAOS-8). BENE generates the map FROM the
database — agents, capabilities + autonomy levels, skills, memory domains,
recent engram activity, entry-point commands — so it cannot rot. This is the
~100-line map-not-encyclopedia an incoming agent reads first.
"""

from __future__ import annotations

import json
from typing import Any

SECTIONS = (
    "agents",
    "capabilities",
    "skills",
    "memory_domains",
    "recent_activity",
    "entry_points",
)

ENTRY_POINTS = [
    {"command": "bene ls", "purpose": "list agents"},
    {"command": "bene senses --json", "purpose": "this manifest"},
    {"command": "bene logs <agent_id>", "purpose": "agent event history"},
    {"command": "bene memory search <q> / bene skills search <q>", "purpose": "shared knowledge"},
    {"command": "bene retrieve <q>", "purpose": "entropy-routed multi-tier retrieval (MemGAS)"},
    {"command": "bene trust <agent_id>", "purpose": "computed trust summary"},
    {"command": "bene experiments ls", "purpose": "probe/evolution journal"},
    {"command": "bene spec ls", "purpose": "SDD proposals + acceptance gating status"},
    {
        "command": "bene evolve continual status <agent>",
        "purpose": "in-episode genome swap history",
    },
    {
        "command": "bene consolidate run --policy nightly",
        "purpose": "cron-spawnable memory consolidation",
    },
    {"command": "bene replay ls", "purpose": "exportable signed deterministic replay runs"},
    {"command": "bene observe status", "purpose": "which trace backend the runner uses"},
    {"command": "bene checkpoint/diff/restore", "purpose": "the Litany loop"},
]


class SensesManifest:
    @staticmethod
    def generate(bene: Any, *, fmt: str = "json") -> str:
        conn = bene.conn
        data: dict[str, Any] = {}

        data["agents"] = [
            {"agent_id": r[0], "name": r[1], "status": r[2]}
            for r in conn.execute(
                "SELECT agent_id, name, status FROM agents ORDER BY created_at DESC LIMIT 25"
            ).fetchall()
        ]
        try:
            data["capabilities"] = [
                {"name": r[0], "autonomy_level": r[1], "description": r[2]}
                for r in conn.execute(
                    "SELECT name, autonomy_level, description FROM capabilities ORDER BY name"
                ).fetchall()
            ]
        except Exception:  # noqa: BLE001 — v2 tables absent on a pure-legacy db
            data["capabilities"] = []
        data["skills"] = [
            {"name": r[0], "description": r[1]}
            for r in conn.execute(
                "SELECT name, description FROM agent_skills ORDER BY created_at DESC LIMIT 25"
            ).fetchall()
        ]
        data["memory_domains"] = [
            {"type": r[0], "count": r[1]}
            for r in conn.execute(
                "SELECT type, COUNT(*) FROM memory GROUP BY type ORDER BY 2 DESC"
            ).fetchall()
        ]
        try:
            data["recent_activity"] = [
                {"kind": r[0], "count": r[1]}
                for r in conn.execute(
                    "SELECT kind, COUNT(*) FROM engrams GROUP BY kind ORDER BY 2 DESC"
                ).fetchall()
            ]
        except Exception:  # noqa: BLE001
            data["recent_activity"] = []
        data["entry_points"] = ENTRY_POINTS

        if fmt == "json":
            return json.dumps(data, indent=1, default=str)
        # markdown: the human-readable map
        lines = ["# BENE senses — generated from the live database", ""]
        for section in SECTIONS:
            lines.append(f"## {section}")
            entries = data[section]
            if not entries:
                lines.append("(none)")
            for e in entries:
                lines.append("- " + ", ".join(f"{k}={v}" for k, v in e.items()))
            lines.append("")
        return "\n".join(lines)
