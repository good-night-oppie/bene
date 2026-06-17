"""Fixture tests for PROBE-EXEC-01 install-resolves (exec_probes.py).

Covers the exemption matrix for a first-party install command:
  - PUBLISHED first-party (bene, on PyPI since 2026-06-16) → resolves outright,
    no disclosure or source spec needed.
  - unpublished first-party → needs a resolvable source spec OR an honest
    not-yet-published disclosure within the ±_PROXIMITY de-tagged window (the
    <br/>/<span> line-split that HTML imposes on a <Terminal> block), else BLOCK.

The disclosure / source-spec / window tests force the unpublished path (PUBLISHED
emptied via the `unpublished` fixture) so they exercise that logic rather than
short-circuiting on the published exemption.
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


@pytest.fixture
def unpublished(probes, monkeypatch):
    """Force the unpublished-first-party path so the disclosure / source-spec /
    window logic is exercised — bene is in PUBLISHED by default, which would
    short-circuit before any of that."""
    monkeypatch.setattr(probes, "PUBLISHED", frozenset())
    return probes


# The real hero/footer <Terminal> block: disclosure two source lines above the
# install, split by <br/>.
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

# Bare install, no disclosure / source spec → must BLOCK for an unpublished pkg.
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


def test_published_first_party_exempt(probes):
    # bene is in PUBLISHED (on PyPI since 2026-06-16) → a bare `pip install bene`
    # resolves outright; no disclosure or source spec required.
    assert probes.scan_install_text("site/index.html", BARE_INSTALL) == []


def test_disclosed_terminal_block_en_passes(unpublished):
    assert unpublished.scan_install_text("site/index.html", DISCLOSED_TERMINAL_EN) == []


def test_disclosed_terminal_block_zh_passes(unpublished):
    assert unpublished.scan_install_text("site/zh/index.html", DISCLOSED_TERMINAL_ZH) == []


def test_bare_unpublished_install_blocks(unpublished):
    findings = unpublished.scan_install_text("site/index.html", BARE_INSTALL)
    assert len(findings) == 1
    assert findings[0].probe == "PROBE-EXEC-01"
    assert findings[0].severity == "BLOCK"


def test_source_spec_passes(unpublished):
    assert unpublished.scan_install_text("docs/install.md", SOURCE_SPEC) == []


def test_third_party_ignored(probes):
    assert probes.scan_install_text("docs/install.md", THIRD_PARTY) == []


def test_disclosure_beyond_window_blocks(unpublished):
    findings = unpublished.scan_install_text("site/index.html", DISCLOSURE_TOO_FAR)
    assert len(findings) == 1
