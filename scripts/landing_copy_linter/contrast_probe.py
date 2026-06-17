#!/usr/bin/env python3
"""contrast_probe.py — WCAG-AA contrast checker for the BENE landing tokens.

A new dimension for the accuracy/quality gate (bene-core-3): make text contrast a
CHECKED invariant so the "muted on cream" / "orange on cream" accessibility
regressions can't recur. Pairs with exec_probes.py — same gate, new dimension.

The ONE hard part is FP avoidance, and the landing's CSS makes it tractable:
color tokens are CONTEXT-DEPENDENT — `--muted` is `#62666D` at `:root` (light,
on the cream `--bg`) but `#A49D9A` under `.section-inverted` / dark theme (on the
dark `#1F1D1C` bg). So a NAIVE cross-product ("`#A49D9A` text on cream = 2.3:1")
is a FALSE POSITIVE: that pair never renders. This probe is SCOPE-AWARE — it
pairs each text token ONLY with the background of the scope it is actually
defined for, exactly the guard bene-core-3 asked for ("don't cross-product;
only pair with the bg actually rendered on; exempt the dark terminal blocks").

It also only flags tokens used AS TEXT (`text-bene-<token>` in the HTML), so
divider/border tokens (`--dim`, `--med`) that legitimately have low contrast as
hairlines are not flagged.

Thresholds (WCAG AA): BLOCK below 3:1 (fails even large/bold text); WARN 3:1–4.5:1
(fails normal text but may be acceptable for >=24px/bold). Without per-element
size we don't hard-BLOCK the 3:1–4.5:1 band — that keeps the gate FP-safe.

Run:   uv run python scripts/landing_copy_linter/contrast_probe.py [--json]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANDING = REPO / "site" / "index.html"

BLOCK_RATIO = 3.0  # below this: fails even large/bold text -> BLOCK
WARN_RATIO = 4.5  # below this: fails normal text -> WARN (ok if >=24px/bold)


@dataclass
class Finding:
    probe: str
    severity: str  # "BLOCK" | "WARN"
    file: str
    detail: str


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def _triple_to_hex(triple: str) -> str | None:
    m = re.match(r"\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\s*$", triple)
    if not m:
        return None
    return "#" + "".join(f"{int(x):02X}" for x in m.groups())


def _hex_of(value: str) -> str | None:
    """Resolve a CSS color value that is either `#hex` or `R G B`."""
    value = value.strip()
    m = re.search(r"#([0-9A-Fa-f]{3,6})\b", value)
    if m:
        return "#" + m.group(1)
    return _triple_to_hex(value)


# A scope = a {token: hex} map + a resolved background hex.
def _parse_scopes(css: str) -> list[tuple[str, str, dict[str, str]]]:
    """Return [(scope_name, bg_hex, {token: fg_hex})]. Models the two scopes a
    reader actually sees: the light :root page (cream bg) and the inverted
    section (dark bg). Dark-theme tokens render on the dark bg and pass, so the
    light page + inverted section are the contrast-critical scopes."""

    def block(selector_re: str) -> str:
        m = re.search(selector_re + r"\s*\{([^}]*)\}", css, re.S)
        return m.group(1) if m else ""

    root = block(r":root(?:\s*,\s*:root\[data-theme=\"light\"\])?")
    root_tokens = {f"--{k}": _hex_of(v) for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", root)}
    root_tokens = {k: v for k, v in root_tokens.items() if v}
    page_bg = root_tokens.get("--bg")

    # .section-inverted overrides: own background + per-token color rules
    inv_bg = (
        _hex_of(
            re.search(r"\.section-inverted\s*\{[^}]*background\s*:\s*([^;]+);", css, re.S).group(1)
        )
        if re.search(r"\.section-inverted\s*\{[^}]*background", css, re.S)
        else None
    )
    inv_tokens = dict(root_tokens)
    for tok, col in re.findall(
        r"\.section-inverted\s+\.text-bene-([\w-]+)\s*\{\s*color\s*:\s*([^;]+);", css
    ):
        h = _hex_of(col)
        if h:
            inv_tokens[f"--{tok}"] = h

    scopes = []
    if page_bg:
        scopes.append(("light page (cream)", page_bg, root_tokens))
    if inv_bg:
        scopes.append((".section-inverted (dark)", inv_bg, inv_tokens))
    return scopes


# tailwind text-class -> css var token (the names match: text-bene-muted -> --muted)
_TEXT_CLASS_RE = re.compile(r"text-bene-([\w-]+)")


def run(landing: Path = LANDING) -> list[Finding]:
    if not landing.exists():
        return []
    html = landing.read_text(errors="replace")
    try:
        rel = str(landing.relative_to(REPO))
    except ValueError:
        rel = landing.name
    scopes = _parse_scopes(html)
    used = {m.group(1) for m in _TEXT_CLASS_RE.finditer(html)}  # tokens used AS TEXT
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for scope_name, bg, tokens in scopes:
        for tok in sorted(used):
            fg = tokens.get(f"--{tok}")
            if not fg or not bg:
                continue
            key = (fg.upper(), bg.upper())
            if key in seen:
                continue
            seen.add(key)
            r = contrast_ratio(fg, bg)
            if r >= WARN_RATIO:
                continue
            sev = "BLOCK" if r < BLOCK_RATIO else "WARN"
            findings.append(
                Finding(
                    "PROBE-CONTRAST",
                    sev,
                    rel,
                    f"text-bene-{tok} {fg} on {scope_name} bg {bg} = {r}:1 "
                    f"(< {WARN_RATIO}:1 WCAG-AA normal text).",
                )
            )
    return findings


def run_all() -> dict:
    findings = run()
    blocks = [f for f in findings if f.severity == "BLOCK"]
    return {
        "findings": [asdict(f) for f in findings],
        "failure_count": len(blocks),
        "warn_count": len(findings) - len(blocks),
    }


def main() -> int:
    res = run_all()
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2))
    else:
        for f in res["findings"]:
            print(f"[{f['severity']}] {f['probe']} {f['file']} — {f['detail']}")
        print(f"\nfailures (BLOCK): {res['failure_count']}  warnings: {res['warn_count']}")
    return 1 if res["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
