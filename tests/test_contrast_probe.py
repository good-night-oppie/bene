"""Tests for contrast_probe.py — WCAG-AA scope-aware contrast checker.

Locks the load-bearing FP guard: a color token defined differently per scope
(`--muted` is light on the cream :root but a different value under
`.section-inverted`/dark) must be paired ONLY with the bg of the scope it is
defined for. The naive cross-product ("dark-scope text on the cream page") must
NOT flag — that pair never renders. Also locks the contrast math and that only
text-used tokens are considered.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROBE = REPO / "scripts" / "landing_copy_linter" / "contrast_probe.py"


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("contrast_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["contrast_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


# A miniature landing with the same scope structure as site/index.html:
# - :root light page, cream bg, a low-contrast accent and a fine text colour
# - .section-inverted dark scope where --muted is REDEFINED to a value that would
#   FAIL on cream but PASSES on its own dark bg (the cross-product trap).
FIXTURE = """
<style>
:root {
  --bg: 240 238 232;     /* #F0EEE8 cream */
  --text: 31 29 28;      /* #1F1D1C ok on cream */
  --accent: 238 96 24;   /* #EE6018 burnt orange -> 2.86 on cream (BLOCK) */
  --muted: 98 102 109;   /* #62666D -> 4.97 on cream (ok) */
}
body { background: rgb(var(--bg)); color: rgb(var(--text)); }
.section-inverted { background: #1F1D1C; color: #EDE9E4; }
.section-inverted .text-bene-muted { color: #A49D9A; } /* 2.3 on cream BUT 6.29 on dark */
</style>
<span className="text-bene-text">fine</span>
<span className="text-bene-accent">low contrast accent</span>
<div className="section-inverted"><span className="text-bene-muted">dark-scope muted</span></div>
"""


def test_contrast_math(probe):
    assert probe.contrast_ratio("#EE6018", "#F0EEE8") == 2.86
    assert probe.contrast_ratio("#A49D9A", "#1F1D1C") == 6.29
    assert probe.contrast_ratio("#A49D9A", "#F0EEE8") == 2.3  # the FP pairing's ratio


def test_scope_aware_and_findings(probe, tmp_path):
    landing = tmp_path / "index.html"
    landing.write_text(FIXTURE)
    findings = probe.run(landing)
    details = " ".join(f.detail for f in findings)

    # the real low-contrast accent on the cream page IS flagged
    assert any("EE6018" in f.detail and "cream" in f.detail.lower() for f in findings), details
    # the cross-product FP (dark-scope #A49D9A paired with cream) is NOT flagged
    assert not any("A49D9A" in f.detail and "cream" in f.detail.lower() for f in findings), details
    # the dark-scope muted, paired with its OWN dark bg, passes (6.29) -> not flagged
    assert not any("A49D9A" in f.detail for f in findings), details
    # a token that passes on cream (#62666D 4.97, and #1F1D1C text) is not flagged
    assert not any("62666D" in f.detail for f in findings), details


def test_block_vs_warn_severity(probe, tmp_path):
    landing = tmp_path / "index.html"
    landing.write_text(FIXTURE)
    accent = [f for f in probe.run(landing) if "EE6018" in f.detail]
    assert accent and accent[0].severity == "BLOCK"  # 2.86 < 3.0 -> BLOCK
