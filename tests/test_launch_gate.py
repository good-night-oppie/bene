"""Regression tests for scripts/launch_gate.py (review 2026-06-19 follow-ups).

These pin the four reviewer-found gate gaps so a future edit can't silently
re-introduce them:

  CID 3433944241  --live mode must fetch + assert the LIVE landing version, not
                  only the local site/index.html.
  CID 3433944251  canonical-repo check must match a whole path segment, so a
                  same-prefix mirror (good-night-oppie/bene-site) is rejected.
  CID 3433944255  the zh honest-banner source check must assert the visible
                  per-page fallback banner element, not just the ambiguous
                  title-suffix token.
  CID 3433944258  priority zh docs must be version-fresh, not merely present —
                  a stale `0.2.0` in a translation must fail the gate.

launch_gate.py lives in scripts/ (not an installed package), so it is loaded by
path. Its file readers (_read/_http_get) are monkeypatched per test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GATE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "launch_gate.py"
_spec = importlib.util.spec_from_file_location("launch_gate", _GATE_PATH)
assert _spec and _spec.loader
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


REPO_VERSION = "0.2.1"


@pytest.fixture
def patched(monkeypatch):
    """Drive the gate off in-memory source/HTTP fixtures.

    Returns a small handle: set `.files[rel] = text` and `.urls[url] = text`,
    then build a Gate and call the check functions.
    """

    files: dict[str, str] = {}
    urls: dict[str, str] = {}

    def fake_read(rel: str) -> str:
        if rel not in files:
            raise FileNotFoundError(rel)
        return files[rel]

    def fake_http(url: str) -> str:
        if url not in urls:
            raise RuntimeError(f"unstubbed url {url}")
        return urls[url]

    monkeypatch.setattr(lg, "_read", fake_read)
    monkeypatch.setattr(lg, "_http_get", fake_http)
    monkeypatch.setattr(lg, "repo_version", lambda: REPO_VERSION)

    class Handle:
        pass

    h = Handle()
    h.files = files
    h.urls = urls
    return h


# ── CID 3433944251 — canonical repo boundary ────────────────────────────────
def test_canonical_repo_rejects_same_prefix_mirror():
    # the OLD substring test ('good-night-oppie/bene' in text) would accept this:
    text = "see github.com/good-night-oppie/bene-site for marketing"
    assert lg.CANONICAL_REPO_RE.search(text) is None


def test_canonical_repo_accepts_exact_path():
    for ok in (
        "github.com/good-night-oppie/bene",
        "github.com/good-night-oppie/bene ",
        "github.com/good-night-oppie/bene/issues",
        "good-night-oppie/bene#readme",
    ):
        assert lg.CANONICAL_REPO_RE.search(ok) is not None, ok


def test_check_llms_canonical_fails_on_same_prefix_only(patched):
    # llms.txt that points ONLY at the bene-site mirror must fail (no real canonical).
    patched.files["site/llms.txt"] = "repo: github.com/good-night-oppie/bene-site\n"
    g = lg.Gate()
    lg.check_llms_canonical(g, live_base=None)
    assert g.failures, "same-prefix-only llms.txt must fail the canonical check"


# ── CID 3433944241 — --live validates live landing version ──────────────────
def test_version_check_live_catches_stale_deployed_landing(patched):
    rv = REPO_VERSION
    patched.files["site/index.html"] = f"BENE v{rv}"
    patched.files["site/zh/index.html"] = f"BENE v{rv}"
    base = "https://example.test/bene"
    # local pages are current, but the LIVE deploy still serves an old version:
    patched.urls[base + "/"] = "BENE v0.2.0"
    patched.urls[base + "/zh/"] = "BENE v0.2.0"

    g = lg.Gate()
    lg.check_version_triple_match(g, check_pypi=False, live_base=base)
    assert any("LIVE" in f and "0.2.0" in f for f in g.failures), (
        f"live stale landing version must fail; failures={g.failures}"
    )


def test_version_check_live_passes_when_deploy_is_current(patched):
    rv = REPO_VERSION
    patched.files["site/index.html"] = f"BENE v{rv}"
    patched.files["site/zh/index.html"] = f"BENE v{rv}"
    base = "https://example.test/bene"
    patched.urls[base + "/"] = f"BENE v{rv}"
    patched.urls[base + "/zh/"] = f"BENE v{rv}"

    g = lg.Gate()
    lg.check_version_triple_match(g, check_pypi=False, live_base=base)
    assert not g.failures, g.failures


# ── CID 3433944258 — zh priority docs version freshness ─────────────────────
_GOOD_BUILDER = (
    'title_suffix = "中文索引 / 翻译中"\n'
    '<div class="zh-banner">本页中文版正在按照 4-book methodology 翻译</div>\n'
    "page = f'{banner}'\n"
)


def test_doc_semver_regex_catches_backticked_bare_version():
    # docs cite `0.2.0`, not v0.2.0 — the doc regex must catch it.
    assert lg.SEMVER_IN_DOC.findall("还是 `0.2.0`；") == ["0.2.0"]
    assert lg.SEMVER_IN_DOC.findall("打进 `0.2.1` 包") == ["0.2.1"]
    # prose numbers without backticks are NOT versions (avoid false positives):
    assert lg.SEMVER_IN_DOC.findall("see section 1.2.3 below") == []


def test_check3_fails_on_stale_zh_doc_version(tmp_path, monkeypatch):
    # Build a throwaway ROOT with the real check3 disk layout.
    root = tmp_path
    (root / "site").mkdir()
    (root / "site" / "build-docs.py").write_text(_GOOD_BUILDER, encoding="utf-8")
    zh = root / "docs" / "zh"
    zh.mkdir(parents=True)
    (zh / "README.md").write_text("no version here", encoding="utf-8")
    (zh / "cli-reference.md").write_text("no version here", encoding="utf-8")
    # stale: repo is 0.2.1, doc still cites `0.2.0`
    (zh / "integrating-bene.md").write_text("还是 `0.2.0`；", encoding="utf-8")

    monkeypatch.setattr(lg, "ROOT", root)
    monkeypatch.setattr(lg, "repo_version", lambda: REPO_VERSION)
    g = lg.Gate()
    lg.check_cn_no_fake_promises(g, live_base=None)
    assert any("integrating-bene.md" in f and "0.2.0" in f for f in g.failures), g.failures


def test_check3_passes_on_fresh_zh_docs(tmp_path, monkeypatch):
    root = tmp_path
    (root / "site").mkdir()
    (root / "site" / "build-docs.py").write_text(_GOOD_BUILDER, encoding="utf-8")
    zh = root / "docs" / "zh"
    zh.mkdir(parents=True)
    (zh / "README.md").write_text("no version", encoding="utf-8")
    (zh / "cli-reference.md").write_text("no version", encoding="utf-8")
    (zh / "integrating-bene.md").write_text("打进 `0.2.1` 包", encoding="utf-8")

    monkeypatch.setattr(lg, "ROOT", root)
    monkeypatch.setattr(lg, "repo_version", lambda: REPO_VERSION)
    g = lg.Gate()
    lg.check_cn_no_fake_promises(g, live_base=None)
    assert not g.failures, g.failures


# ── CID 3433944255 — zh honest-banner mechanism completeness ─────────────────
def test_check3_fails_when_visible_banner_element_removed(tmp_path, monkeypatch):
    # title-suffix token present, but the VISIBLE per-page banner is gone.
    builder_missing_banner = 'title_suffix = "中文索引 / 翻译中"\npage = "no banner here"\n'
    root = tmp_path
    (root / "site").mkdir()
    (root / "site" / "build-docs.py").write_text(builder_missing_banner, encoding="utf-8")
    zh = root / "docs" / "zh"
    zh.mkdir(parents=True)
    for d in lg.ZH_PRIORITY_DOCS:
        (zh / d).write_text("no version", encoding="utf-8")

    monkeypatch.setattr(lg, "ROOT", root)
    monkeypatch.setattr(lg, "repo_version", lambda: REPO_VERSION)
    g = lg.Gate()
    lg.check_cn_no_fake_promises(g, live_base=None)
    assert any("honest-banner mechanism is incomplete" in f for f in g.failures), g.failures
