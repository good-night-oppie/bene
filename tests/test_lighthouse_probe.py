"""Tests for ``examples/lighthouse_trace_probe.py`` — the PASS-31 reproduction.

Asserts the example demonstrates the exact kill-gate behavior the framework-help
roadmap promises: a shape gate (``isinstance``-style) registers inadmissible and
runs VOID, while a falsifiable ``propagated_true >= 1`` probe REJECTs the broken
(propagation=False) subject and ACCEPTs the fixed (propagation=True) subject.
"""

from __future__ import annotations

from examples.lighthouse_trace_probe import (
    FALSIFIABLE_GATE,
    main,
    measure,
    run_lighthouse,
)


def test_measure_models_shape_vs_semantics():
    # The shape metric is the same for broken and fixed (the bug the bad test missed)...
    assert measure(False)["is_bool"] == measure(True)["is_bool"] == 1.0
    # ...while the semantic metric distinguishes them.
    assert measure(False)["propagated_true"] == 0.0
    assert measure(True)["propagated_true"] == 1.0


def test_lighthouse_reproduces_pass31():
    r = run_lighthouse()
    # Shape gate: a gate the baseline already passes cannot falsify -> VOID.
    assert r["shape_status"] == "inadmissible"
    assert r["shape_verdict"] == "VOID"
    # Falsifiable gate: authored buggy-incumbent-must-fail -> admissible.
    assert r["probe_status"] == "admissible"
    # It catches the broken env and clears the real fix.
    assert r["broken_verdict"] == "REJECT"
    assert FALSIFIABLE_GATE["name"] in r["broken_killed"]
    assert r["fixed_verdict"] == "ACCEPT"


def test_example_main_exits_zero():
    # The example is its own check: main() returns 0 only when all five outcomes hold.
    assert main() == 0
