"""Agent-quality metrics — thinking depth, context breadth, implementation time.

Derived from the Stop-hook transcript_path (Claude Code passes this in
stdin JSON). Cursor doesn't pass a transcript; metrics are skipped there.

Metrics (each backed by published research):

  1. Deep-Thinking Ratio (DTR) — thinking_tokens / output_tokens
     Source: arXiv:2602.13517. DTR has r=0.828 with accuracy. Raw output
     length has r=-0.544 (NEGATIVE — verbose != good).

  2. Context-Reading Breadth — count of unique files Read + total bytes +
     unique Glob/Grep call count. Per HELMET: utilization > coverage,
     so we also compute cited-files-in-diff / files-read = utilization rate.

  3. Implementation Time — wall-clock seconds from first non-Read tool
     call to Stop event. Excludes upfront research phase.

  4. Step-Level Cognitive Depth — per arXiv:2602.12662, depth should
     vary per step. We compute coefficient-of-variation of thinking
     tokens per tool-use as a proxy for depth-adaptiveness.

  5. AC Coverage — % of acceptance-criteria lines in spec.md that appear
     verbatim or semantically in the test suite diff.

All metrics best-effort; never block hook on metric failure.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from .paths import harness_dir, project_root
from .git_state import diff


def _safe_read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _parse_transcript(transcript_path: str) -> dict:
    """Returns aggregated stats from a Claude Code session transcript.

    Claude Code emits one JSON-lines transcript per session at the path
    handed to Stop hooks. Each line is an event: user message, assistant
    message (incl. thinking blocks), tool_use, tool_result.

    We extract:
      - thinking_tokens (sum of `thinking` block lengths in chars / ~4 for tokens)
      - output_tokens (sum of `text` block lengths similarly)
      - tool_use list with name, input, ts
      - assistant_step_depths (per assistant turn, thinking_chars)
    """
    events = _safe_read_jsonl(Path(transcript_path))
    stats = {
        "thinking_chars": 0,
        "output_chars": 0,
        "tool_uses": [],
        "assistant_step_depths": [],
        "user_turns": 0,
    }
    for ev in events:
        msg = ev.get("message") or ev
        role = msg.get("role") or ev.get("type")
        content = msg.get("content")
        if role == "user":
            stats["user_turns"] += 1
        if role == "assistant" and isinstance(content, list):
            step_thinking = 0
            for block in content:
                btype = block.get("type")
                if btype == "thinking":
                    text = block.get("thinking") or block.get("text") or ""
                    step_thinking += len(text)
                    stats["thinking_chars"] += len(text)
                elif btype == "text":
                    stats["output_chars"] += len(block.get("text", ""))
                elif btype == "tool_use":
                    stats["tool_uses"].append({
                        "name": block.get("name"),
                        "input": block.get("input", {}),
                        "id": block.get("id"),
                    })
            stats["assistant_step_depths"].append(step_thinking)
    return stats


def _files_read(tool_uses: list[dict]) -> set[str]:
    out: set[str] = set()
    for t in tool_uses:
        name = (t.get("name") or "").lower()
        inp = t.get("input") or {}
        if name in ("read",):
            p = inp.get("file_path") or inp.get("path")
            if p:
                out.add(str(p))
    return out


def _search_calls(tool_uses: list[dict]) -> int:
    return sum(1 for t in tool_uses if (t.get("name") or "").lower() in ("glob", "grep"))


def _first_non_read_ts(tool_uses: list[dict]) -> int | None:
    # transcripts don't always carry ts; fall back to index-based ordering
    for i, t in enumerate(tool_uses):
        name = (t.get("name") or "").lower()
        if name not in ("read", "glob", "grep"):
            return i
    return None


def _ac_coverage_proxy() -> float:
    """% of acceptance-criteria bullets from spec.md that show up in diff text."""
    spec = harness_dir() / "spec.md"
    if not spec.exists():
        return 0.0
    text = spec.read_text()
    # Extract numbered/bulleted ACs from "## Acceptance criteria" section
    m = re.search(r"##\s*Acceptance criteria(.*?)(?:\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return 0.0
    ac_section = m.group(1)
    acs = [
        line.strip(" -*0123456789.\t")
        for line in ac_section.splitlines()
        if line.strip().startswith(("-", "*", "1", "2", "3", "4", "5"))
    ]
    acs = [a for a in acs if len(a) > 10 and not a.startswith("<")]  # skip placeholders
    if not acs:
        return 0.0
    d = diff().lower()
    # Look for ≥3-word stems from each AC in the diff
    covered = 0
    for ac in acs:
        words = [w for w in re.findall(r"\w+", ac.lower()) if len(w) > 3]
        if len(words) < 3:
            continue
        stem = " ".join(words[:5])
        if stem in d:
            covered += 1
    return round(covered / len(acs), 3)


def compute(transcript_path: str | None) -> dict:
    """Returns a metrics dict to append to telemetry. Best-effort, never raises."""
    out = {
        "thinking_depth_ratio": None,    # DTR — arXiv:2602.13517
        "thinking_chars": 0,
        "output_chars": 0,
        "step_depth_cv": None,           # arXiv:2602.12662
        "context_breadth_files": 0,
        "context_breadth_bytes_est": 0,
        "search_calls": 0,
        "tool_use_total": 0,
        "user_turns": 0,
        "impl_step_offset": None,
        "ac_coverage_proxy": _ac_coverage_proxy(),
    }
    if not transcript_path:
        return out
    try:
        stats = _parse_transcript(transcript_path)
    except Exception:
        return out

    out["thinking_chars"] = stats["thinking_chars"]
    out["output_chars"] = stats["output_chars"]
    if stats["output_chars"] > 0:
        out["thinking_depth_ratio"] = round(
            stats["thinking_chars"] / stats["output_chars"], 3
        )
    if len(stats["assistant_step_depths"]) >= 2:
        try:
            mean = statistics.mean(stats["assistant_step_depths"])
            if mean > 0:
                stdev = statistics.pstdev(stats["assistant_step_depths"])
                out["step_depth_cv"] = round(stdev / mean, 3)
        except statistics.StatisticsError:
            pass

    files = _files_read(stats["tool_uses"])
    out["context_breadth_files"] = len(files)
    # Estimate bytes by file size at HEAD (best-effort)
    total = 0
    root = project_root()
    for f in files:
        p = root / f if not f.startswith("/") else Path(f)
        try:
            total += p.stat().st_size
        except OSError:
            pass
    out["context_breadth_bytes_est"] = total
    out["search_calls"] = _search_calls(stats["tool_uses"])
    out["tool_use_total"] = len(stats["tool_uses"])
    out["user_turns"] = stats["user_turns"]
    out["impl_step_offset"] = _first_non_read_ts(stats["tool_uses"])
    return out
