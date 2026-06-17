"""Fixture tests for PROBE-EXEC-01 install-resolves proximity (exec_probes.py).

Locks the site/index.html:938 + site/zh/index.html:927 false positive: an
honest not-yet-published disclosure (`# coming to PyPI — early access`) in the
SAME <Terminal> block, two source lines above `pip install bene` and split by
`<br/>`, must EXEMPT the install — while a bare `pip install bene` with no
disclosure anywhere near it must still BLOCK. Without the de-tagged ±N-line
window the disclosure was invisible (the guard only saw the single raw line)
and the hero/footer install was wrongly flagged.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = REPO_ROOT / "scripts" / "landing_copy_linter" / "exec_probes.py"


@pytest.fixture(scope="module")
def probes():
    spec = importlib.util.spec_from_file_location("exec_probes_under_test", PROBE_PATH)
    assert spec and spec.loader, "could not load exec_probes.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["exec_probes_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# The real hero/footer <Terminal> block from site/index.html: disclosure two
# source lines above the install, split by <br/> (the FP that motivated the fix).
DISCLOSED_TERMINAL_EN = """\
        <Terminal>
          <span className="text-bene-muted"># coming to PyPI — early access</span>
          <br />
          pip install bene
          <br />
          uv run bene init && uv run bene demo --no-ui
        </Terminal>"""

DISCLOSED_TERMINAL_ZH = """\
        <Terminal>
          <span className="text-bene-muted"># 即将上 PyPI — early access</span>
          <br />
          pip install bene
          <br />
          uv run bene init
        </Terminal>"""

# Bare install, no disclosure and no source spec anywhere near it → must BLOCK.
BARE_INSTALL = """\
        <Terminal>
          pip install bene
          <br />
          uv run bene init
        </Terminal>"""

# Resolvable via explicit source spec → exempt (different exemption path).
SOURCE_SPEC = "uv pip install bene --index https://example.test/simple\n"

# Third-party packages are never first-party → never flagged.
THIRD_PARTY = "uv add httpx\npip install pytest\n"

# Disclosure further than ±_PROXIMITY source lines away must NOT mask the broken
# install (locks the window boundary so the exemption can't be over-broadened).
DISCLOSURE_TOO_FAR = "\n".join(
    ["<span># coming to PyPI — early access</span>"] + ["<br/>"] * 12 + ["pip install bene"]
)


def test_disclosed_terminal_block_en_passes(probes):
    assert probes.scan_install_text("site/index.html", DISCLOSED_TERMINAL_EN) == []


def test_disclosed_terminal_block_zh_passes(probes):
    assert probes.scan_install_text("site/zh/index.html", DISCLOSED_TERMINAL_ZH) == []


def test_bare_install_blocks(probes):
    findings = probes.scan_install_text("site/index.html", BARE_INSTALL)
    assert len(findings) == 1
    assert findings[0].probe == "PROBE-EXEC-01"
    assert findings[0].severity == "BLOCK"


def test_source_spec_passes(probes):
    assert probes.scan_install_text("docs/install.md", SOURCE_SPEC) == []


def test_third_party_ignored(probes):
    assert probes.scan_install_text("docs/install.md", THIRD_PARTY) == []


def test_disclosure_beyond_window_blocks(probes):
    findings = probes.scan_install_text("site/index.html", DISCLOSURE_TOO_FAR)
    assert len(findings) == 1
