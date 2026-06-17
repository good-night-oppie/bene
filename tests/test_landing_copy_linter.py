"""Tests for the BENE landing-copy linter (regex + KILL_LIST + allowlist)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENTRYPOINT = SCRIPTS_DIR / "landing_copy_linter.py"


@pytest.fixture(scope="module")
def linter_module():
    """Load the entrypoint as a module so we can call scan_text/_glob_to_regex
    directly without spawning a subprocess for every test."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("landing_copy_linter_main", ENTRYPOINT)
    assert spec and spec.loader, "could not load linter entrypoint"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["landing_copy_linter_main"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Per-rule fixture cases — (rule_id, text, expected_hit_count)
#
# Each rule has at least one should_block + one should_pass case.
# should_pass cases verify we have not over-broadened the regex so it silently
# fires on legitimate verb-shaped prose.
# ---------------------------------------------------------------------------
RULE_CASES: list[tuple[str, str, str, int]] = [
    # ─── KILL_LIST literals (short-circuit BLOCK) ─────────────────────────
    ("KILL_LIST", "trust-is-computed-literal", "trust is computed", 1),
    ("KILL_LIST", "trust-verb-form-passes", "Run `bene trust show <agent>`.", 0),
    ("KILL_LIST", "not-declared-literal", "Trust ledger — not declared, just shipped", 1),
    ("KILL_LIST", "kanban-misuse", "看板 跑得飞起", 1),
    ("KILL_LIST", "kanban-correct-term", "仪表盘 跑得飞起", 0),
    ("KILL_LIST", "plumbing-literal", "剩下的就是接管子", 1),
    ("KILL_LIST", "plumbing-correct", "剩下的就是接入数据", 0),
    ("KILL_LIST", "pillars-capitalized", "These are the Pillars of BENE.", 1),
    ("KILL_LIST", "pillars-lowercase-passes-killlist", "These are the pillars of BENE.", 0),
    ("KILL_LIST", "base-zh-substrate", "BENE 把这些事拢进一个 基座", 1),
    ("KILL_LIST", "white-send-marketing", "BENE 白送你这些", 1),
    ("KILL_LIST", "real-runs-claim", "都真实跑过", 1),
    # The KILL_LIST literal "one X = one Y" is the placeholder template, not
    # the instantiation. Instantiated text ("one agent = one SQLite") is
    # caught by BENE-LINT-001 alternation 3, not KILL_LIST.
    ("KILL_LIST", "x-equals-y-template-literal", "one X = one Y", 1),
    ("KILL_LIST", "x-equals-y-instantiation-passes-killlist", "one agent = one SQLite", 0),
    ("KILL_LIST", "zh-x-equals-y", "一个 agent = 一份 SQLite", 1),
    # 飞轮 / 硬核 — slop a model-authored rewrite proposal tried to introduce
    # while claiming to remove 装逼 metaphor (2026-06-15 redesign rejection).
    ("KILL_LIST", "feilun-flywheel", "BENE 把失败和成功拧成一个数据飞轮。", 1),
    ("KILL_LIST", "yinghe-hardcore", "四个硬核原语。", 1),
    ("KILL_LIST", "loop-concrete-passes", "赢的输的都落进 bene.db，成为下一轮的输入。", 0),
    # ─── BENE-LINT-001 — x-equals-y reductive (BLOCK) ────────────────────
    ("BENE-LINT-001", "x-equals-y-bene-runtime", "BENE is a runtime for agents.\n", 1),
    (
        "BENE-LINT-001",
        "x-equals-y-verb-rewrite",
        "Run BENE as a Python library, a CLI, or an MCP server.\n",
        0,
    ),
    ("BENE-LINT-001", "x-not-y-comma-form", "Isolation is structural, not ACL maintenance.\n", 1),
    # ─── BENE-LINT-002 — count-named heading + lockstep body (BLOCK) ──────
    (
        "BENE-LINT-002",
        "h2-named-count",
        '<h2 className="font-display">Four invariants the harness will not bend on</h2>',
        1,
    ),
    (
        "BENE-LINT-002",
        "h2-no-count",
        '<h2 className="font-display">Invariants the harness will not bend on</h2>',
        0,
    ),
    # ─── BENE-LINT-003 — section-lead preamble (WARN) ─────────────────────
    (
        "BENE-LINT-003",
        "section-lead-preamble",
        "## The Gap\n\nNone of these is a knock on the existing stacks; here's what the research moved past.\n",
        1,
    ),
    (
        "BENE-LINT-003",
        "section-lead-scene",
        "## The Gap\n\nAt 3 a.m. the on-call opens the dashboard and the agent has just blown a deploy.\n",
        0,
    ),
    # ─── BENE-LINT-004 — writer-warm noun jargon (WARN) ───────────────────
    ("BENE-LINT-004", "substrate-noun", "BENE provides a substrate for engrams.\n", 1),
    ("BENE-LINT-004", "concrete-artifact", "BENE writes engrams to a single bene.db file.\n", 0),
    # ─── BENE-LINT-010 — x=y reductive recidivism (BLOCK) ─────────────────
    ("BENE-LINT-010", "doctrine-recidivism", "trust is computed, not declared\n", 1),
    ("BENE-LINT-010", "x-is-one-y", "BENE is one substrate for many agents.\n", 1),
    (
        "BENE-LINT-010",
        "verb-shaped-fact",
        "Run `bene trust show <agent>` and 4 signals come back.\n",
        0,
    ),
    # ─── BENE-LINT-012 — killed-word resurrection (WARN) ──────────────────
    ("BENE-LINT-012", "pillars-resurrected", "BENE rests on five pillars.\n", 1),
    ("BENE-LINT-012", "pillars-rewritten", "BENE rests on five concrete capabilities.\n", 0),
    # ─── BENE-LINT-015 — install command without copy button (WARN) ───────
    ("BENE-LINT-015", "uv-add-no-copy", "<Terminal>uv add bene && uv run bene init</Terminal>", 1),
    (
        "BENE-LINT-015",
        "uv-add-with-copy-after",
        "<Terminal>uv add bene && uv run bene init</Terminal>\n"
        '<button data-copy="uv add bene">Copy</button>',
        0,
    ),
    # ─── BENE-LINT-017 — agent-pronoun microcopy (WARN) ───────────────────
    ("BENE-LINT-017", "your-agent-microcopy", "Paste this into your agent.\n", 1),
    ("BENE-LINT-017", "concrete-verb", "Run `uv add bene` and start a fresh run.\n", 0),
    # ─── BENE-LINT-019 — cn-style x=y (WARN) ──────────────────────────────
    (
        "BENE-LINT-019",
        "cn-x-is-not-y",
        "trust is computed from evidence, not granted by a YAML\n",
        1,
    ),
    ("BENE-LINT-019", "cn-x-verb-form", "Run `bene trust show <agent>` to see the composite\n", 0),
    # ─── BENE-LINT-026 — zh code-switch gloss density (WARN) ──────────────
    (
        "BENE-LINT-026",
        "zh-four-gloss-overload",
        '<p className="font-sans">先跑 offline eval「离线评测」，再看 regression「回归问题」，'
        "接着 pipeline「流水线」，最后 harness「框架」。</p>",
        1,
    ),
    (
        "BENE-LINT-026",
        "zh-two-gloss-ok",
        '<p className="font-sans">先跑 offline eval「离线评测」，再看 regression「回归问题」就够了。</p>',
        0,
    ),
]


@pytest.mark.parametrize(
    "rule_id,case_id,text,expected_hits",
    RULE_CASES,
    ids=[f"{r}::{name}" for (r, name, _, _) in RULE_CASES],
)
def test_per_rule_fixture(linter_module, rule_id, case_id, text, expected_hits):
    """For each rule fixture, scan the text and assert hit count matches.

    `case_id` is purely for human-readable test naming — assertions check
    `rule_id` only because the linter's verdict is keyed on the rule that
    fired, not on the fixture slug.
    """
    violations = linter_module.scan_text("fixture.md", text)
    matching = [v for v in violations if v.rule_id == rule_id]
    assert len(matching) == expected_hits, (
        f"rule={rule_id} fixture={case_id} expected={expected_hits} "
        f"got={len(matching)}; all violations={[(v.rule_id, v.match[:60]) for v in violations]}"
    )


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,pattern,expected",
    [
        ("site/docs/p.html", "site/docs/**/*.html", True),
        ("site/docs/sub/p.html", "site/docs/**/*.html", True),
        ("site/docs/p.html", "site/docs/*.html", True),
        ("site/index.html", "site/docs/**/*.html", False),
        ("a/b/.git/HEAD", "**/.git/**", True),
        ("node_modules/foo/bar.js", "**/node_modules/**", True),
        ("foo/__pycache__/x.pyc", "**/__pycache__/**", True),
        ("README.md", "site/docs/*.html", False),
        ("site/SKILL.md", "site/SKILL.md", True),
        ("site/design-explorations/v2.html", "site/design-explorations/**", True),
    ],
)
def test_glob_to_regex(linter_module, path, pattern, expected):
    assert bool(linter_module._glob_to_regex(pattern).match(path)) is expected


# ---------------------------------------------------------------------------
# Dir-fixture regression walker
#
# tests/fixtures/landing_copy_linter/<rule_id>/{should_block,should_pass}/*.html
#
# Each file in should_block MUST cause <rule_id> to fire at least once.
# Each file in should_pass MUST NOT cause <rule_id> to fire.
#
# Locked-in regression seeded by harness-6 2026-06-15: site/zh/index.html L867
# slop ("Dune 比喻... 这个顺序才稳。每一个 X 都能落到一个真的 Y") silently
# passed all 4 rules that should have caught it. Each of 002/004/009/019 now
# has the verbatim line as its zh-line-867 fixture.
# ---------------------------------------------------------------------------
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "landing_copy_linter"


def _discover_fixtures(category: str):
    if not FIXTURES_ROOT.is_dir():
        return []
    out = []
    for rule_dir in sorted(FIXTURES_ROOT.iterdir()):
        if not rule_dir.is_dir():
            continue
        cat_dir = rule_dir / category
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.iterdir()):
            if f.is_file():
                out.append((rule_dir.name, f))
    return out


@pytest.mark.parametrize(
    "rule_id,path",
    _discover_fixtures("should_block"),
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_fixture_should_block(linter_module, rule_id, path):
    text = path.read_text(encoding="utf-8")
    violations = linter_module.scan_text(str(path), text)
    matching = [v for v in violations if v.rule_id == rule_id]
    assert matching, (
        f"fixture {path.relative_to(REPO_ROOT)} expected to BLOCK {rule_id} "
        f"but rule never fired; all violations={[(v.rule_id, v.match[:60]) for v in violations]}"
    )


@pytest.mark.parametrize(
    "rule_id,path",
    _discover_fixtures("should_pass"),
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_fixture_should_pass(linter_module, rule_id, path):
    text = path.read_text(encoding="utf-8")
    violations = linter_module.scan_text(str(path), text)
    matching = [v for v in violations if v.rule_id == rule_id]
    assert not matching, (
        f"fixture {path.relative_to(REPO_ROOT)} expected to PASS {rule_id} "
        f"but rule fired: matching={[(v.match[:60], v.line) for v in matching]}"
    )


def test_allowlist_silences_match(linter_module, tmp_path):
    """If a violation matches an allowlist entry (file + line + rule_id +
    justification + future expires), is_allowed must return True."""
    Violation = linter_module.Violation
    v = Violation(
        rule_id="BENE-LINT-010",
        severity="BLOCK",
        file="site/index.html",
        line=897,
        col=1,
        match="Fear is the mind-killer.",
        prompt_hint="(unused in this test)",
        doctrine="(unused)",
        kind="rule",
    )
    allowlist = [
        {
            "file": "site/index.html",
            "line": 897,
            "rule_id": "BENE-LINT-010",
            "justification": "verbatim Frank Herbert Litany Against Fear",
            "expires": "2030-01-01",
        }
    ]
    assert linter_module.is_allowed(v, allowlist, "2026-06-15") is True
    # Expired entry must NOT silence.
    expired = [dict(allowlist[0], expires="2020-01-01")]
    assert linter_module.is_allowed(v, expired, "2026-06-15") is False
    # Entry missing justification must NOT silence.
    no_just = [{k: v for k, v in allowlist[0].items() if k != "justification"}]
    assert linter_module.is_allowed(v, no_just, "2026-06-15") is False
    # Different line must NOT silence (when allowlist anchors the line).
    other_line = Violation(**{**v.__dict__, "line": 1000})
    assert linter_module.is_allowed(other_line, allowlist, "2026-06-15") is False


def test_allowlist_match_contains_survives_line_drift(linter_module):
    """A match_contains entry silences the violation regardless of line, but
    only when the matched text contains the anchor substring."""
    Violation = linter_module.Violation
    base = dict(
        rule_id="BENE-LINT-010",
        severity="BLOCK",
        file="site/index.html",
        col=1,
        prompt_hint="(unused)",
        doctrine="(unused)",
        kind="rule",
    )
    allowlist = [
        {
            "file": "site/index.html",
            "match_contains": "Fear is the",
            "rule_id": "BENE-LINT-010",
            "justification": "verbatim Litany Against Fear",
            "expires": "2030-01-01",
        }
    ]
    # Same verse at two very different lines → both silenced (line drift proof).
    v897 = Violation(**base, line=897, match="Fear is the mind-killer.")
    v922 = Violation(
        **base, line=922, match="Fear is the little-death that brings total obliteration."
    )
    assert linter_module.is_allowed(v897, allowlist, "2026-06-15") is True
    assert linter_module.is_allowed(v922, allowlist, "2026-06-15") is True
    # A genuine X=Y on a different line whose text lacks the anchor → NOT silenced.
    real = Violation(**base, line=40, match="BENE is a runtime for AI coding agents.")
    assert linter_module.is_allowed(real, allowlist, "2026-06-15") is False


def test_kill_list_short_circuits_allowlist(linter_module):
    """KILL_LIST hits use rule_id="KILL_LIST"; if a per-rule allowlist for a
    BENE-LINT rule happens to cover the same offset, the KILL_LIST hit must
    NOT be silenced (only an entry with rule_id=KILL_LIST can silence it)."""
    violations = linter_module.scan_text("site/index.html", "trust is computed\n")
    kill_hits = [v for v in violations if v.rule_id == "KILL_LIST"]
    assert kill_hits, "KILL_LIST must fire on 'trust is computed'"
    # Empty allowlist → BLOCK.
    assert not linter_module.is_allowed(kill_hits[0], [], "2026-06-15")
    # Per-rule allowlist for a different rule must NOT silence the KILL_LIST.
    other_rule = [
        {
            "file": "site/index.html",
            "rule_id": "BENE-LINT-001",
            "justification": "unrelated",
            "expires": "2030-01-01",
        }
    ]
    assert not linter_module.is_allowed(kill_hits[0], other_rule, "2026-06-15")


# ---------------------------------------------------------------------------
# End-to-end CLI tests
# ---------------------------------------------------------------------------
def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the linter via uv run from the repo root."""
    cmd = ["uv", "run", "python", str(ENTRYPOINT)] + list(args)
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_exits_zero_on_clean_input(tmp_path):
    """A file with no recidivism patterns and no killed literals → exit 0."""
    clean = tmp_path / "clean.md"
    clean.write_text(
        "# A clean section\n\n"
        "Run `uv add bene` to install. Open `bene.db` with sqlite3 to inspect engrams.\n"
    )
    proc = _run_cli(str(clean), "--no-default-paths")
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"


def test_cli_exits_one_on_kill_list_hit(tmp_path):
    """A file containing a KILL_LIST literal → exit 1."""
    dirty = tmp_path / "dirty.md"
    dirty.write_text("# Doctrine\n\ntrust is computed, not declared\n")
    proc = _run_cli(str(dirty), "--no-default-paths")
    assert proc.returncode == 1, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "KILL_LIST" in proc.stderr
    assert "trust is computed" in proc.stderr


def test_cli_json_output_parses(tmp_path):
    """--json output must be valid JSON."""
    dirty = tmp_path / "dirty.md"
    dirty.write_text("BENE is a runtime.\n")
    proc = _run_cli("--json", str(dirty), "--no-default-paths")
    data = json.loads(proc.stdout)
    assert isinstance(data, list)
    assert any(v["rule_id"] == "BENE-LINT-001" for v in data)


def test_cli_default_targets_resolve_to_landing_surface():
    """No-args invocation must resolve to the canonical landing target set."""
    proc = _run_cli("--json")
    data = json.loads(proc.stdout)
    files_seen = {v["file"] for v in data}
    # No targets means default globs ran — there might be 0 violations after
    # cleanup, but the SET of touched files is bounded to the landing surface.
    LANDING_SURFACE = {
        "site/index.html",
        "site/zh/index.html",
        "site/SKILL.md",
        "site/llms.txt",
        "README.md",
    }
    assert files_seen.issubset(LANDING_SURFACE), (
        f"Linter walked beyond the landing surface: {files_seen - LANDING_SURFACE}"
    )


def test_cli_today_envvar_drives_expiry(tmp_path):
    """LANDING_COPY_LINTER_TODAY overrides date.today() so the expiry logic
    is testable without time travel."""
    import os

    dirty = tmp_path / "dirty.md"
    dirty.write_text("BENE is a runtime for AI coding agents.\n")
    allowlist = tmp_path / "allow.yaml"
    # "BENE is a runtime..." fires BOTH BENE-LINT-001 and BENE-LINT-010;
    # allowlist both so the test isolates the expiry behaviour.
    allowlist.write_text(
        "entries:\n"
        "  - file: dirty.md\n"
        "    rule_id: BENE-LINT-001\n"
        "    justification: test\n"
        "    expires: '2026-01-01'\n"
        "  - file: dirty.md\n"
        "    rule_id: BENE-LINT-010\n"
        "    justification: test\n"
        "    expires: '2026-01-01'\n"
    )
    # Today before expiry → silenced
    env = os.environ.copy()
    env["LANDING_COPY_LINTER_TODAY"] = "2025-06-15"
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(ENTRYPOINT),
            str(dirty),
            "--no-default-paths",
            "--allowlist",
            str(allowlist),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, f"expected silenced; stderr={proc.stderr}"
    # Today after expiry → fires
    env["LANDING_COPY_LINTER_TODAY"] = "2027-06-15"
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(ENTRYPOINT),
            str(dirty),
            "--no-default-paths",
            "--allowlist",
            str(allowlist),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 1, f"expected fired; stdout={proc.stdout} stderr={proc.stderr}"


# ---------------------------------------------------------------------------
# Sanity: the canonical landing surface is currently green.
# ---------------------------------------------------------------------------
def test_canonical_landing_surface_is_green():
    """The actual landing files must exit 0 with the committed allowlist.

    If this fails: either fix the copy or add an allowlist entry per the
    dispatch ironclad. Editing rules.py to silence the linter is forbidden.
    """
    proc = _run_cli("--json")
    blocks = [v for v in json.loads(proc.stdout) if v["severity"] == "BLOCK"]
    assert not blocks, "Canonical landing surface has BLOCKs:\n" + "\n".join(
        f"  {v['file']}:{v['line']}  [{v['rule_id']}]" for v in blocks
    )
    assert proc.returncode == 0
