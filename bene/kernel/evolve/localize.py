"""Critical-step localizer — earliest decisive error in a failed trajectory.

Mechanism idea ported from "Where LLM Agents Fail and How They Can Learn From
Failures" (arXiv:2509.25370): when an agent fails, the *visible* error is
rarely the *decisive* one — the agent usually locked in a wrong direction
several steps earlier and only paid for it later. The localizer therefore
points at the EARLIEST decisive step strictly before the first visible error,
not at the step where the error finally surfaced.

Discipline: heuristic-first, LLM-fallback. The deterministic scorer handles
the common shapes for free; an optional ``llm_call_fn`` (a plain callable —
wire to bene/router providers if desired, never litellm, never the openai
SDK) is consulted only when the heuristic confidence is below the floor, and
its answer is cached by trajectory-SHAPE fingerprint so two structurally
identical failures pay the model cost once.

This module is data-free and general: the only constants are ordinary English
mutation verbs / generic decision event types (configurable classifier
defaults) and the fixed confidence-formula coefficients, identical for any
input. Persistence is engram-native (tier-1 episodic, D1/D2) — no new tables,
no new engram kinds.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from bene.kernel.engrams import EngramStore, UnknownEngram

#: Tool-name substrings that "lock in" a direction — a wrong write-ish call is
#: far more decisive than a wrong read-only lookup. General mutation verbs,
#: not dataset-derived; override per-domain via ``decisive_tool_hints=``.
DEFAULT_TOOL_HINTS: tuple[str, ...] = (
    "write",
    "save",
    "delete",
    "deploy",
    "apply",
    "exec",
    "run",
    "create",
    "update",
    "merge",
    "push",
)

#: Log/event types that commit the agent to a direction. Generic coordination
#: vocabulary; override per-domain via ``decisive_log_types=``.
DEFAULT_LOG_TYPES: frozenset[str] = frozenset({"intent", "vote", "decision", "commit"})

#: Confidence-formula coefficients (mechanism constants, identical for any
#: input): Case A fixed confidence; Case B base + per-step-gap slope +
#: per-extra-decision slope, capped. See :func:`_heuristic_localize`.
_CASE_A_CONFIDENCE = 0.7
_CASE_B_BASE = 0.55
_CASE_B_GAP_SLOPE = 0.05
_CASE_B_DECISION_SLOPE = 0.04
_CASE_B_CAP = 0.9

#: Below this heuristic confidence the optional LLM fallback is consulted.
DEFAULT_HEURISTIC_FLOOR = 0.6

_LABEL_LIMIT = 80  # chars of summary/error carried into a step label


@dataclass
class Step:
    """One point on a merged, chronological agent timeline.

    ``kind`` is the source channel (conventionally ``"tool"`` | ``"log"`` |
    ``"event"``); ``ref`` is an opaque provenance id (engram id / event seq /
    tool call id) so blame stays provenance-linked.
    """

    kind: str
    label: str
    is_error: bool
    is_decision: bool
    ref: Any = None
    ts: str = ""  # ISO timestamp, only used as an ordering fallback


@dataclass
class Localization:
    """The localizer's verdict: which step decided the failure, and why."""

    index: int  # index into the merged step list
    step: Step  # the blamed step
    rationale: str
    method: str  # "heuristic" | "llm" | "llm-cached"
    confidence: float


# ---------------- step classification ----------------


def classify_tool(
    name: str,
    status: str | None = None,
    error_message: str | None = None,
    *,
    decisive_tool_hints: Sequence[str] = DEFAULT_TOOL_HINTS,
    ref: Any = None,
    ts: str = "",
) -> Step:
    """Classify a tool call into a :class:`Step`.

    Error: ``status == "error"`` or a non-empty ``error_message``. Decision:
    the lowercased tool name contains any decisive hint (substring match).
    """
    is_error = (status == "error") or bool(error_message)
    lowered = (name or "").lower()
    label = f"tool:{name}"
    if error_message:
        label += f" ERROR {error_message[:_LABEL_LIMIT]}"
    return Step(
        kind="tool",
        label=label,
        is_error=is_error,
        is_decision=any(h in lowered for h in decisive_tool_hints),
        ref=ref,
        ts=ts,
    )


def classify_event(
    event_type: str,
    summary: str = "",
    *,
    decisive_log_types: Iterable[str] = DEFAULT_LOG_TYPES,
    ref: Any = None,
    ts: str = "",
) -> Step:
    """Classify a log/event entry into a :class:`Step`.

    Error: type ``"abort"``. Decision: type in ``decisive_log_types``.
    """
    return Step(
        kind="log",
        label=f"log:{event_type} {summary[:_LABEL_LIMIT]}".strip(),
        is_error=event_type == "abort",
        is_decision=event_type in decisive_log_types,
        ref=ref,
        ts=ts,
    )


def merge_timeline(steps: Iterable[Step]) -> list[Step]:
    """Merge multi-channel steps into one chronological timeline.

    Fallback ordering for channels that lack a shared sequence: stable sort by
    ``(ts, channel)`` with non-tool channels sorting BEFORE ``tool`` on
    timestamp ties, so an intent precedes the tool call it triggered. Sources
    with a native total order (e.g. the append-only events journal sequence)
    should be passed pre-ordered and skip this.
    """
    return sorted(steps, key=lambda s: (s.ts, 1 if s.kind == "tool" else 0))


# ---------------- the heuristic ----------------


def _heuristic_localize(steps: Sequence[Step]) -> tuple[int, str, float] | None:
    """Return ``(index, rationale, confidence)`` or None.

    Find the first error. The EARLIEST decision step strictly before it is the
    prime suspect — a wrong decision the agent only paid for later. Decisions
    at/after the first error never shadow an earlier one; if no decision
    precedes the error, the error step itself is the critical step (Case A).

    Case B confidence rises with the gap between the decisive step and the
    visible error (a bug that festered N steps is a clearer "earliest
    critical" signal) and with how many decisions piled up before the error;
    capped, rounded to 3 decimals.
    """
    if not steps:
        return None
    first_err_idx = next((i for i, s in enumerate(steps) if s.is_error), None)
    if first_err_idx is None:
        return None  # nothing failed — nothing to localize

    decisions_before = [i for i in range(first_err_idx) if steps[i].is_decision]
    if not decisions_before:
        label = steps[first_err_idx].label
        return (
            first_err_idx,
            f"No decisive step preceded the failure; the error at `{label}`"
            " is itself the critical step.",
            _CASE_A_CONFIDENCE,
        )

    earliest = decisions_before[0]
    gap = first_err_idx - earliest
    confidence = round(
        min(
            _CASE_B_CAP,
            _CASE_B_BASE
            + _CASE_B_GAP_SLOPE * gap
            + _CASE_B_DECISION_SLOPE * (len(decisions_before) - 1),
        ),
        3,
    )
    return (
        earliest,
        f"Earliest decisive step before the failure: `{steps[earliest].label}`"
        f" ({gap} step(s) before the visible error). The agent locked in this"
        " direction here; later steps inherited it.",
        confidence,
    )


# ---------------- optional LLM fallback ----------------

_LLM_PROMPT = """You are localizing the EARLIEST decisive error in a failed AI agent trajectory.

The visible error is rarely the root cause — the agent usually went wrong earlier and only paid \
for it later. Identify the single step where the outcome was effectively decided.

Trajectory (chronological, 0-indexed):
{trace}

Respond as STRICT JSON with exactly these keys:
  "index":      integer step number of the earliest critical step
  "rationale":  one sentence explaining why that step decided the outcome
  "confidence": float in [0,1]

Return the JSON object and nothing else."""


def trace_fingerprint(steps: Sequence[Step]) -> str:
    """Stable hash over the SHAPE of the trace (kinds + error/decision flags),
    not the contents — two structurally identical failures share a cache slot."""
    shape = "|".join(f"{s.kind}:{int(s.is_error)}{int(s.is_decision)}" for s in steps)
    return hashlib.sha256(shape.encode("utf-8", "replace")).hexdigest()[:16]


def _render_trace(steps: Sequence[Step]) -> str:
    return "\n".join(
        f"{i}: [{s.kind}]{' ERR' if s.is_error else ''}"
        f"{' DECISIVE' if s.is_decision else ''} {s.label}"
        for i, s in enumerate(steps)
    )


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Parse a strict-JSON reply, tolerating prose around one JSON object."""
    for candidate in (raw, raw[raw.find("{") : raw.rfind("}") + 1]):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _llm_localize(
    steps: Sequence[Step], call_fn: Callable[[str], str]
) -> tuple[int, str, float] | None:
    """Ask the model for the critical index; None on any failure (the caller
    then keeps the heuristic answer)."""
    try:
        raw = call_fn(_LLM_PROMPT.format(trace=_render_trace(steps)))
    except Exception:
        return None
    parsed = _parse_llm_json(raw)
    if not parsed:
        return None
    try:
        index = int(parsed.get("index"))  # type: ignore[arg-type]
        confidence = float(parsed.get("confidence", 0.6) or 0.6)
    except (TypeError, ValueError):
        return None
    if not 0 <= index < len(steps):
        return None
    return index, str(parsed.get("rationale") or "LLM localization."), confidence


# ---------------- driver ----------------


def localize_steps(
    steps: Sequence[Step],
    *,
    llm_call_fn: Callable[[str], str] | None = None,
    heuristic_floor: float = DEFAULT_HEURISTIC_FLOOR,
    cache: MutableMapping[str, Any] | None = None,
) -> Localization | None:
    """Localize the earliest decisive step in a failed trajectory.

    Pure and deterministic by default: no I/O, no LLM, no DB. Returns None for
    an empty trajectory or one with no error step.

    The LLM (if ``llm_call_fn`` given) is consulted only when the heuristic
    confidence is below ``heuristic_floor``; with the default floor the
    heuristic always clears it, so the fallback exists for callers who raise
    the floor. LLM answers are cached in the injected mapping-like ``cache``
    under ``"localize:" + trace_fingerprint(steps)``; a hit yields
    ``method="llm-cached"``. Any LLM failure falls back to the heuristic.
    """
    steps = list(steps)
    heuristic = _heuristic_localize(steps)
    if heuristic is None:
        return None
    index, rationale, confidence = heuristic
    method = "heuristic"

    if confidence < heuristic_floor and llm_call_fn is not None:
        key = "localize:" + trace_fingerprint(steps)
        cached = cache.get(key) if cache is not None else None
        answer: tuple[int, str, float] | None = None
        if cached is not None:
            try:
                answer = (int(cached[0]), str(cached[1]), float(cached[2]))
            except (TypeError, ValueError, IndexError, KeyError):
                answer = None
            if answer is not None and 0 <= answer[0] < len(steps):
                index, rationale, confidence = answer
                method = "llm-cached"
            else:
                answer = None
        if method == "heuristic" and answer is None:
            llm = _llm_localize(steps, llm_call_fn)
            if llm is not None:
                index, rationale, confidence = llm
                method = "llm"
                if cache is not None:
                    cache[key] = (index, rationale, confidence)

    return Localization(
        index=index,
        step=steps[index],
        rationale=rationale,
        method=method,
        confidence=confidence,
    )


# ---------------- engram conveniences ----------------


def steps_from_engrams(
    store: EngramStore,
    engram_ids: Sequence[str],
    *,
    decisive_tool_hints: Sequence[str] = DEFAULT_TOOL_HINTS,
    decisive_log_types: Iterable[str] = DEFAULT_LOG_TYPES,
) -> list[Step]:
    """Thin adapter: classify trace engrams into Steps, in the order given.

    The caller's id order defines the timeline (engram ids are monotonic
    ULIDs, so chronological fetch order is the natural choice). Tool-shaped
    engrams are recognized by ``metadata["tool_name"]``/``metadata["tool"]``
    (plus optional ``status``/``error_message``); anything else is treated as
    a log/event whose type comes from ``metadata["entry_type"]`` /
    ``metadata["type"]`` or the title's leading ``type:`` segment (the mirror
    title convention, e.g. ``shared_log:intent:7``). ``ref`` carries the
    engram id so the blame is provenance-linked.
    """
    steps: list[Step] = []
    for engram_id in engram_ids:
        engram = store.get(engram_id)
        meta = engram.metadata
        tool = meta.get("tool_name") or meta.get("tool")
        if tool:
            steps.append(
                classify_tool(
                    str(tool),
                    status=meta.get("status"),
                    error_message=meta.get("error_message"),
                    decisive_tool_hints=decisive_tool_hints,
                    ref=engram_id,
                    ts=engram.created_at,
                )
            )
            continue
        title = engram.title
        if title.startswith("shared_log:"):
            title = title.split(":", 1)[1]
        event_type = str(meta.get("entry_type") or meta.get("type") or title.split(":", 1)[0])
        steps.append(
            classify_event(
                event_type,
                summary=engram.title,
                decisive_log_types=decisive_log_types,
                ref=engram_id,
                ts=engram.created_at,
            )
        )
    return steps


def persist_localization(
    store: EngramStore,
    localization: Localization,
    *,
    provenance: dict[str, Any],
    agent_id: str | None = None,
    source_ids: Sequence[str] | None = None,
) -> str:
    """Persist a Localization as a tier-1 episodic engram (D1/D2: everything
    is an engram — no new table, no new kind).

    Links ``derived_from`` → each source engram. When ``source_ids`` is None,
    the blamed step's ``ref`` is used if it names an existing engram (the
    :func:`steps_from_engrams` case).
    """
    if source_ids is None:
        sources = [localization.step.ref] if isinstance(localization.step.ref, str) else []
    else:
        sources = list(source_ids)
    parents: list[str] = []
    for sid in sources:
        try:
            store.get(sid)
        except UnknownEngram:
            continue
        parents.append(sid)
    payload = json.dumps(
        {
            "type": "critical_step",
            "index": localization.index,
            "rationale": localization.rationale,
            "confidence": localization.confidence,
            "method": localization.method,
        }
    )
    return store.append(
        "episodic",
        f"critical_step:{localization.index}:{localization.step.label[:_LABEL_LIMIT]}",
        payload,
        tier=1,
        provenance=provenance,
        agent_id=agent_id,
        parents=parents,
        link_type="derived_from",
        metadata={
            "type": "critical_step",
            "method": localization.method,
            "confidence": localization.confidence,
        },
    )
