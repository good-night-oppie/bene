"""Context-pollution detection + consolidate-then-recover (the Litany loop).

"LLMs Get Lost in Multi-Turn Conversation" (SYNTHESIS: agent-theory #03):
once an agent commits to a wrong path, the contaminated context keeps
misleading it — recap does NOT recover; consolidating requirements into a
fresh context does. Neither rival detects this state (GAP-AUDIT KAOS-4,
BENE-6).

Deterministic, documented signals (pluggable scorer interface):
- ``repeated_failed_calls`` — ≥N failed tool calls against the same target;
- ``error_rate_spike``     — error fraction in the window above threshold;
- ``contradiction_markers`` — explicit self-contradiction phrases in traces.

Recovery wraps the LEGACY checkpoint API (never ports it): consolidate the
requirements from the trace, emit a pollution engram, then restore the latest
pre-contamination checkpoint — face the fear, let it pass, only the clean
context remains.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import ulid

from bene.kernel.engrams import EngramStore
from bene.kernel.memory.rehighlight import EvidenceRehighlighter, RehighlightedContext

REPEATED_FAIL_THRESHOLD = 3
ERROR_RATE_THRESHOLD = 0.5
CONTAMINATION_THRESHOLD = 0.5
CONTRADICTION_MARKERS = (
    "actually no",
    "wait, that's wrong",
    "contradicts",
    "as i said before",  # answer-bloat / premature-commitment signal
)


@dataclass
class PollutionReport:
    agent_id: str
    score: float
    signals: dict[str, Any] = field(default_factory=dict)
    polluted: bool = False
    window: int = 0


class PollutionDetector:
    SIGNALS = ("repeated_failed_calls", "error_rate_spike", "contradiction_markers")

    def __init__(self, store: EngramStore, *, scorer=None) -> None:
        self.store = store
        self._scorer = scorer  # optional override: Callable[[dict], float]

    # ---------------- detection ----------------

    def scan(self, agent_id: str, *, window: int = 50) -> PollutionReport:
        conn = self.store.conn
        calls = conn.execute(
            "SELECT tool_name, input, status FROM tool_calls WHERE agent_id = ?"
            " ORDER BY started_at DESC LIMIT ?",
            (agent_id, window),
        ).fetchall()

        # signal 1: repeated failures against the same (tool, input) target
        failed_targets = Counter(
            (tool, inp) for tool, inp, status in calls if status in ("error", "timeout")
        )
        max_repeat = max(failed_targets.values(), default=0)
        repeated = max_repeat >= REPEATED_FAIL_THRESHOLD

        # signal 2: error-rate spike in the window
        terminal = [s for _, _, s in calls if s in ("success", "error", "timeout")]
        error_rate = sum(1 for s in terminal if s != "success") / len(terminal) if terminal else 0.0
        spike = error_rate > ERROR_RATE_THRESHOLD

        # signal 3: contradiction markers in recent trace engrams
        rows = conn.execute(
            "SELECT inline_body FROM engrams WHERE agent_id = ? AND kind='trace'"
            " AND inline_body IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (agent_id, window),
        ).fetchall()
        text = " ".join(r[0].lower() for r in rows)
        contradictions = sum(text.count(m) for m in CONTRADICTION_MARKERS)

        signals = {
            "repeated_failed_calls": {"max_repeat": max_repeat, "tripped": repeated},
            "error_rate_spike": {"error_rate": round(error_rate, 4), "tripped": spike},
            "contradiction_markers": {"count": contradictions, "tripped": contradictions >= 2},
        }
        if self._scorer is not None:
            score = float(self._scorer(signals))
        else:
            score = sum(0.4 if s["tripped"] else 0.0 for s in signals.values())
        return PollutionReport(
            agent_id=agent_id,
            score=round(score, 4),
            signals=signals,
            polluted=score >= CONTAMINATION_THRESHOLD,
            window=window,
        )

    # ---------------- recovery ----------------

    def consolidate_requirements(self, agent_id: str, *, limit: int = 30) -> str:
        """Compress the agent's recent intent from its traces — the
        fresh-context payload (the paper's working recovery)."""
        rows = self.store.conn.execute(
            "SELECT title FROM engrams WHERE agent_id = ? AND kind='trace'"
            " ORDER BY created_at ASC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        lines = [f"- {r[0]}" for r in rows]
        return "REQUIREMENTS (consolidated from trace):\n" + "\n".join(lines)

    def rehighlight(
        self,
        agent_id: str,
        *,
        window: int = 30,
        intent_limit: int = 12,
        requirements: str | None = None,
        rehighlighter: EvidenceRehighlighter | None = None,
    ) -> RehighlightedContext:
        """VEA rung: foreground the recent in-context items that still match the
        agent's INTENT; dim the derailed rest.

        The intent defaults to the consolidated EARLIEST ``intent_limit`` traces
        (the goal, before derailment); pass ``requirements`` to key on an explicit
        goal/query instead. Items are the most recent ``window`` trace/episodic
        engrams (the current, possibly polluted context).

        Read-only — no restore, no writes. The cheap intervention to try before a
        consolidate→restore. ``.evidence_present`` is the escalation gate: when no
        in-context item matches the intent, re-highlighting cannot recover the
        answer and the caller must climb the ladder.
        """
        if requirements is None:
            requirements = self.consolidate_requirements(agent_id, limit=intent_limit)
        rows = self.store.conn.execute(
            "SELECT engram_id, title, COALESCE(inline_body, '') FROM engrams"
            " WHERE agent_id = ? AND kind IN ('trace', 'episodic')"
            " ORDER BY created_at DESC LIMIT ?",
            (agent_id, window),
        ).fetchall()
        items = [{"id": r[0], "text": (r[1] + " " + r[2]).strip()} for r in rows]
        rh = rehighlighter or EvidenceRehighlighter()
        return rh.rehighlight(items, requirements)

    def recover(
        self,
        agent_id: str,
        report: PollutionReport,
        *,
        bene: Any,
        reask: Callable[[RehighlightedContext], bool] | None = None,
        rehighlight_window: int = 30,
        requirements: str | None = None,
    ) -> dict[str, Any]:
        """Walk the recovery ladder: re-highlight → consolidate+restore → respawn.

        Always emits the pollution engram. When ``reask`` is supplied, rung 1 is
        tried first: re-highlight the in-context evidence and let ``reask`` decide
        (the VEA test — did re-asking with it change the outcome?). If evidence is
        present AND ``reask`` returns True, the cheap rung wins and NO restore
        happens. Otherwise (or when ``reask`` is None) it falls through to the
        existing consolidate→restore, respawn-guidance when no checkpoint exists.

        Returns {"intervention", "pollution_engram", "consolidated",
        "restored_checkpoint", "rehighlight"}.
        """
        consolidated = self.consolidate_requirements(agent_id)
        pe = self.store.append(
            "pollution",
            f"pollution:{agent_id} score={report.score}",
            json.dumps({"signals": report.signals, "consolidated": consolidated}, indent=1),
            provenance={"system": "bene.kernel.memory.pollution"},
            agent_id=agent_id,
            metadata={"score": report.score},
        )

        # Rung 1 (cheap, VEA): re-highlight what's already in context, re-ask.
        rehighlight_manifest: dict[str, Any] | None = None
        if reask is not None:
            rctx = self.rehighlight(agent_id, window=rehighlight_window, requirements=requirements)
            rehighlight_manifest = rctx.manifest
            if rctx.evidence_present and bool(reask(rctx)):
                self._record_recovery(agent_id, report, "rehighlight", restored=None)
                return {
                    "intervention": "rehighlight",
                    "pollution_engram": pe,
                    "consolidated": consolidated,
                    "restored_checkpoint": None,
                    "rehighlight": rehighlight_manifest,
                }

        # Rung 2/3 (mid → expensive): restore the latest checkpoint, else respawn.
        checkpoints = bene.list_checkpoints(agent_id)
        restored = None
        if checkpoints:
            restored = checkpoints[-1]["checkpoint_id"]  # latest pre-contamination
            bene.restore(agent_id, restored)
        self._record_recovery(
            agent_id, report, "restore" if restored else "respawn", restored=restored
        )
        return {
            "intervention": "restore" if restored else "respawn",
            "pollution_engram": pe,
            "consolidated": consolidated,
            "restored_checkpoint": restored,
            "rehighlight": rehighlight_manifest,
        }

    def _record_recovery(
        self, agent_id: str, report: PollutionReport, intervention: str, *, restored: str | None
    ) -> None:
        if intervention == "rehighlight":
            summary = (
                f"pollution recovery for {agent_id} (re-highlighted evidence; restore skipped)"
            )
        elif restored:
            summary = f"pollution recovery for {agent_id} (restored {restored})"
        else:
            summary = f"pollution recovery for {agent_id} (respawn advised)"
        self.store.conn.execute(
            "INSERT INTO experiment_runs (run_id, kind, summary, metrics) VALUES (?,?,?,?)",
            (
                str(ulid.new()),
                "consolidation",
                summary,
                json.dumps({"score": report.score, "intervention": intervention}),
            ),
        )
        self.store.conn.commit()
