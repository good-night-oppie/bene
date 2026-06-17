"""Gate specs and evaluation — pre-registered, canonical, hash-locked.

A gate names a metric, a comparison, and a threshold. A gate *passes* when the
subject satisfies it and *kills* otherwise. ``relative_to_baseline`` gates
compare (subject − baseline) against the threshold — these are the gates that
make the identity self-test falsifiable: a candidate identical to its baseline
shows zero improvement and MUST be killed by at least one gate, or the probe
cannot kill anything and is inadmissible (D6: a gate you cannot fail is not a
gate).
"""

from __future__ import annotations

import hashlib
import json
import operator
from typing import Any, TypedDict

OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


class Gate(TypedDict, total=False):
    name: str
    description: str
    metric: str
    op: str  # one of OPS
    threshold: float
    relative_to_baseline: bool


def validate_gates(gates: list[Gate]) -> None:
    if not gates:
        raise ValueError("a probe requires at least one gate")
    for g in gates:
        if not g.get("name") or not g.get("metric"):
            raise ValueError(f"gate missing name/metric: {g!r}")
        if g.get("op") not in OPS:
            raise ValueError(f"gate {g.get('name')}: op must be one of {sorted(OPS)}")
        if not isinstance(g.get("threshold"), (int, float)):
            raise ValueError(f"gate {g.get('name')}: numeric threshold required")


def canonical_spec(gates: list[Gate]) -> str:
    """Deterministic JSON encoding (sorted keys, no whitespace variance)."""
    return json.dumps(sorted((dict(g) for g in gates), key=lambda g: g["name"]), sort_keys=True)


def lock_hash(gates: list[Gate]) -> str:
    return hashlib.sha256(canonical_spec(gates).encode()).hexdigest()


def evaluate_gate(
    gate: Gate,
    subject_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
) -> dict[str, Any]:
    """Returns {name, value, passed, killed}. A missing metric kills (a probe
    that cannot observe its metric must not ACCEPT)."""
    metric = gate["metric"]
    if metric not in subject_metrics:
        return {"name": gate["name"], "value": None, "passed": False, "killed": True}
    value = float(subject_metrics[metric])
    if gate.get("relative_to_baseline"):
        value -= float(baseline_metrics.get(metric, 0.0))
    passed = OPS[gate["op"]](value, float(gate["threshold"]))
    return {"name": gate["name"], "value": value, "passed": passed, "killed": not passed}
