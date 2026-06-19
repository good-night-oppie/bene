#!/usr/bin/env python3
"""BENE public-launch gate (review 2026-06-18, "Day 3").

A small, deterministic readiness check a human or CI runs before flipping
BENE from private preview to public launch. It enforces the three
source-of-truth invariants the reviewer called out — the ones a product
that *sells* provenance/audit-trail discipline must hold on its own
landing/docs/deploy:

  CHECK 1  version triple-match
           every vX.Y.Z on the landing == pyproject.toml version
           (and, with --pypi, == the version published on PyPI)
  CHECK 2  llms.txt points at one canonical repo
           good-night-oppie/bene present, zero EdwardTang/bene-site refs
           (llms.txt is the agent entrypoint — a wrong repo here teaches
            every agent the wrong authoritative source)
  CHECK 3  the Chinese docs do not promise translations that don't exist
           the 中文索引 / 翻译中 honest-banner mechanism is in build-docs.py,
           and the priority zh translations are actually present

Default (no flags) runs the SOURCE checks only — no network, CI-safe.
  --pypi          also assert pyproject version == PyPI's published version
  --live <url>    also assert the LIVE deploy (llms.txt + zh docs index)
  --all  <url>    --pypi and --live together

Exit code is 0 only if every selected check passes; non-zero otherwise.
Stdlib only (tomllib, urllib) so it runs on a fresh checkout with no deps.

Usage:
  python scripts/launch_gate.py
  python scripts/launch_gate.py --pypi
  python scripts/launch_gate.py --all https://agentdex.ai-builders.space/bene
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # bene-main repo root
PYPI_PACKAGE = "bene"
CANONICAL_REPO = "good-night-oppie/bene"
# Match the canonical repo as a whole path segment — a plain substring test would
# accept same-prefix repos like `good-night-oppie/bene-site` or `bene.foo`, which
# are NOT the canonical source. `(?![\w.-])` forbids a trailing repo-name char, and
# `(?<![\w.-])` a leading one (else `evil-good-night-oppie/bene` would satisfy it).
CANONICAL_REPO_RE = re.compile(r"(?<![\w.-])" + re.escape(CANONICAL_REPO) + r"(?![\w.-])")
FORBIDDEN_REPO_TOKEN = "EdwardTang"  # bene-site marketing mirror — never canonical
ZH_PRIORITY_DOCS = ("README.md", "cli-reference.md", "integrating-bene.md")
ZH_HONEST_BANNER = "中文索引 / 翻译中"
SEMVER_ON_PAGE = re.compile(r"v(\d+\.\d+\.\d+)")
# Docs cite the BENE version either as a backtick-quoted bare semver (e.g. `0.2.0`) OR
# as a `bene`-anchored mention in prose (e.g. `bene v0.2.0`, `升级到bene v0.2.0`). The
# second alternative is scoped to a literal `bene` so (a) it still fires when the version
# is glued to Chinese text — a `\w` left-boundary would reject `升级到v0.2.0` since `\w`
# is Unicode-aware — and (b) an unrelated dependency version like `Python v3.10.0` /
# `SQLite v3.45.0` is NOT mistaken for the BENE release and does not fail the gate.
# (PR #88 review.) A bare unprefixed/unanchored x.y.z is never matched.
SEMVER_IN_DOC = re.compile(r"`v?(\d+\.\d+\.\d+)`|(?i:bene)\s*v?(\d+\.\d+\.\d+)")
HTTP_TIMEOUT = 25

# Guard against running from the wrong tree (mirrors build-docs.py's defense):
# a worktree of the bene repo always has the `bene/` package next to scripts/.
if not (ROOT / "bene").is_dir():
    sys.exit(f"launch_gate: ROOT={ROOT} has no bene/ package — run from the bene repo")


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.lines: list[str] = []

    def ok(self, msg: str) -> None:
        self.lines.append(f"  ✓ {msg}")

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        self.lines.append(f"  ✗ {msg}")

    def note(self, msg: str) -> None:
        self.lines.append(f"  · {msg}")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "bene-launch-gate"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310 (trusted urls)
        return resp.read().decode("utf-8", errors="replace")


def repo_version() -> str:
    data = tomllib.loads(_read("pyproject.toml"))
    return data["project"]["version"]


# ── CHECK 1 ────────────────────────────────────────────────────────────────
def check_version_triple_match(g: Gate, *, check_pypi: bool, live_base: str | None = None) -> None:
    g.lines.append("CHECK 1 — version triple-match")
    rv = repo_version()
    g.note(f"pyproject.toml version = {rv}")

    def assert_page_version(label: str, html: str) -> None:
        found = sorted(set(SEMVER_ON_PAGE.findall(html)))
        if not found:
            g.fail(f"{label}: no vX.Y.Z version string found at all")
        elif found == [rv]:
            g.ok(f"{label}: every version string == {rv}")
        else:
            g.fail(f"{label}: version drift — page has {found}, repo is {rv}")

    for page in ("site/index.html", "site/zh/index.html"):
        assert_page_version(page, _read(page))

    if live_base:
        base = live_base.rstrip("/")
        for suffix in ("/", "/zh/"):
            url = base + suffix
            try:
                html = _http_get(url)
            except Exception as e:  # noqa: BLE001
                g.fail(f"LIVE {url}: landing-page fetch failed ({e})")
            else:
                assert_page_version(f"LIVE {url}", html)

    if check_pypi:
        try:
            meta = json.loads(_http_get(f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"))
            pv = meta["info"]["version"]
        except Exception as e:  # noqa: BLE001 — any network/parse error is a skip, reported
            g.fail(f"PyPI check requested but failed to fetch ({e}); cannot confirm triple-match")
        else:
            if pv == rv:
                g.ok(f"PyPI published version == {rv}")
            else:
                g.fail(f"PyPI version {pv} != repo version {rv}")
    else:
        g.note("PyPI check skipped (pass --pypi to include it)")


# ── CHECK 2 ────────────────────────────────────────────────────────────────
def check_llms_canonical(g: Gate, *, live_base: str | None) -> None:
    g.lines.append("CHECK 2 — llms.txt one canonical repo")

    def assert_canonical(label: str, text: str) -> None:
        bad = text.count(FORBIDDEN_REPO_TOKEN)
        if not CANONICAL_REPO_RE.search(text):
            g.fail(f"{label}: canonical repo '{CANONICAL_REPO}' is missing")
        elif bad:
            g.fail(f"{label}: {bad} '{FORBIDDEN_REPO_TOKEN}' ref(s) — must be 0")
        else:
            g.ok(f"{label}: canonical '{CANONICAL_REPO}', 0 '{FORBIDDEN_REPO_TOKEN}'")

    assert_canonical("site/llms.txt", _read("site/llms.txt"))
    if live_base:
        url = live_base.rstrip("/") + "/llms.txt"
        try:
            assert_canonical(f"LIVE {url}", _http_get(url))
        except Exception as e:  # noqa: BLE001
            g.fail(f"LIVE llms.txt fetch failed ({e})")


# ── CHECK 3 ────────────────────────────────────────────────────────────────
def check_cn_no_fake_promises(g: Gate, *, live_base: str | None) -> None:
    g.lines.append("CHECK 3 — Chinese docs promise no translations that don't exist")

    builder = _read("site/build-docs.py")
    # A bare `ZH_HONEST_BANNER in builder` is too weak: that token ('中文索引 /
    # 翻译中') is also the zh title-suffix / index label, so it stays present
    # even if the *visible* per-page fallback banner were deleted. Assert the
    # actual banner-emitting code path instead: the `zh-banner` element, its
    # honest body text, and the template hole (`{banner}`) that renders it onto
    # every untranslated zh page.
    banner_signals = {
        "title suffix label": ZH_HONEST_BANNER in builder,
        "zh-banner element": 'class="zh-banner"' in builder,
        "honest body text": "本页中文版正在按照" in builder,
        "page template hole": "{banner}" in builder,
    }
    missing_signals = [name for name, present in banner_signals.items() if not present]
    if missing_signals:
        g.fail(
            "build-docs.py honest-banner mechanism is incomplete "
            f"(missing: {missing_signals}) — untranslated zh pages would look translated"
        )
    else:
        g.ok(
            "build-docs.py emits the visible per-page zh fallback banner (zh-banner div + body + {banner} hole)"
        )

    rv = repo_version()
    missing = [d for d in ZH_PRIORITY_DOCS if not (ROOT / "docs" / "zh" / d).is_file()]
    if missing:
        g.fail(f"priority zh translations missing: {missing}")
    else:
        g.ok(f"priority zh translations present: {list(ZH_PRIORITY_DOCS)}")
        # Existence is not enough: a stale translation can still ship an old
        # version number (e.g. integrating-bene.md citing 0.2.0 after the repo
        # moved to 0.2.1). Mirror CHECK 1's version-drift discipline on each
        # present doc — any vX.Y.Z it mentions must equal the repo version.
        for d in ZH_PRIORITY_DOCS:
            path = ROOT / "docs" / "zh" / d
            if not path.is_file():
                continue
            found = sorted(
                {
                    m.group(1) or m.group(2)
                    for m in SEMVER_IN_DOC.finditer(
                        path.read_text(encoding="utf-8", errors="replace")
                    )
                }
            )
            drift = [v for v in found if v != rv]
            if drift:
                g.fail(f"docs/zh/{d}: stale version(s) {drift} — repo is {rv}")
            else:
                g.ok(f"docs/zh/{d}: no version drift (versions seen: {found or 'none'})")

    if live_base:
        url = live_base.rstrip("/") + "/zh/docs/"
        try:
            html = _http_get(url)
        except Exception as e:  # noqa: BLE001
            g.fail(f"LIVE zh docs index fetch failed ({e})")
        else:
            if "翻译中" in html or "中文索引" in html:
                g.ok(f"LIVE {url}: carries the honest 翻译中 / 中文索引 label")
            else:
                g.fail(f"LIVE {url}: no honest translation-status label found")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BENE public-launch readiness gate")
    ap.add_argument("--pypi", action="store_true", help="also assert pyproject version == PyPI")
    ap.add_argument(
        "--live",
        metavar="BASE_URL",
        help="also check the live deploy (e.g. https://agentdex.ai-builders.space/bene)",
    )
    ap.add_argument("--all", metavar="BASE_URL", help="shorthand for --pypi --live BASE_URL")
    args = ap.parse_args(argv)

    check_pypi = args.pypi or bool(args.all)
    live_base = args.all or args.live

    g = Gate()
    check_version_triple_match(g, check_pypi=check_pypi, live_base=live_base)
    check_llms_canonical(g, live_base=live_base)
    check_cn_no_fake_promises(g, live_base=live_base)

    print("\n".join(g.lines))
    if g.failures:
        print(f"\n[launch_gate] GATE FAILED — {len(g.failures)} problem(s):")
        for f in g.failures:
            print(f"  - {f}")
        return 1
    print("\n[launch_gate] GATE PASSED — BENE is launch-consistent (selected checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
