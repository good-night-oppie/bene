"""KILL_LIST — literal-string blocklist.

These strings short-circuit BLOCK regardless of regex hits or per-rule
allowlist entries. Each has been killed by the user at least once with a
named correction commit; resurrection is the highest-signal recidivism
signal in the repo's history. Each entry has a `commit` reference so a
future maintainer can read the actual kill rationale before considering
removal.

Hard contract: editing this list to silence the linter is a violation of
the dispatch ironclad. Only the user (via explicit instruction) removes
entries here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KillEntry:
    literal: str
    case_sensitive: bool
    kill_commit: str  # short SHA or descriptive label
    rationale: str


KILL_LIST: list[KillEntry] = [
    KillEntry(
        literal="trust is computed",
        case_sensitive=False,
        kill_commit="recurrent: user-rejected on 2026-06-14 lens-pass and 2026-06-15 audits",
        rationale=(
            "X=Y copula on the contract surface. Trust IS computed in the "
            "code, but on the landing it has to land as a verb the reader "
            "can verify ('bene trust show <agent>'), not a copula tagline."
        ),
    ),
    KillEntry(
        literal="not declared",
        case_sensitive=False,
        kill_commit="2026-06-14 lens-pass-2 + 2026-06-15 audit",
        rationale=(
            "The X-not-Y companion to 'trust is computed'. Pressfield "
            "Client's Disease: defining by negation = defending against a "
            "charge no one made."
        ),
    ),
    KillEntry(
        literal="one X = one Y",
        case_sensitive=False,
        kill_commit="recurrent",
        rationale=(
            "Reductive flattening template (e.g. 'one agent = one SQLite'). "
            "User explicitly named this 句式 (Karpathy X=Y) as a kill-target."
        ),
    ),
    KillEntry(
        literal="一个 agent = 一份 SQLite",
        case_sensitive=False,
        kill_commit="2026-06-13 zh-rewrite-v1 rejected",
        rationale=(
            "Reductive Chinese variant of the X=Y template. User: "
            "'harness is one SQLite 这种煞笔话真的不能忍'."
        ),
    ),
    KillEntry(
        literal="看板",
        case_sensitive=False,
        kill_commit="2026-06-15 user correction",
        rationale=(
            "Wrong translation of 'dashboard' — 看板 is Kanban, "
            "not the live-figures panel. Correct: 仪表盘."
        ),
    ),
    KillEntry(
        literal="接管子",
        case_sensitive=False,
        kill_commit="2026-06-15 user correction",
        rationale=(
            "Literal translation of 'plumbing' that no Chinese engineer "
            "actually uses. Correct framing: '接入数据' / '接 API' / '接线'."
        ),
    ),
    KillEntry(
        literal="都真实跑过",
        case_sensitive=False,
        kill_commit="2026-06-15 demo-label dedup",
        rationale=(
            "Per-card trust label repeated N times — 'show, don't tell' "
            "applied to trust claims: state once, at section level."
        ),
    ),
    KillEntry(
        literal="Pillars",
        case_sensitive=True,
        kill_commit="recurrent BENE2 launch-prose reject",
        rationale=(
            "Marketing-noun structure. User asked for 'verb-over-noun' "
            "framing repeatedly. Capitalized form is the failure mode; "
            "lowercase pillar(s) is covered by BENE-LINT-004."
        ),
    ),
    KillEntry(
        literal="基座",
        case_sensitive=False,
        kill_commit="2026-06-15 section 03 rewrite",
        rationale=(
            "Self-coined Chinese term ('substrate' → 基座). No Chinese "
            "engineer reads 基座 and pictures a SQLite file. Replace with "
            "concrete artifact ('一份 SQLite 文件', 'bene.db')."
        ),
    ),
    KillEntry(
        literal="白送",
        case_sensitive=False,
        kill_commit="2026-06-15 section 03 rewrite",
        rationale=(
            "微商 (multi-level-marketing) tone in 'BENE 白送你这些'. "
            "Direct equivalent: 'BENE 替你管这些'."
        ),
    ),
    KillEntry(
        literal="含金量",
        case_sensitive=False,
        kill_commit="2026-06-15 section 06 self-validation removal",
        rationale=(
            "Self-validation tail ('case study 才算有含金量'). "
            "User: '谁需要你自己肯定自己'. Delete; do not replace."
        ),
    ),
    KillEntry(
        literal="诚实的边界",
        case_sensitive=False,
        kill_commit="2026-06-15 limits H2 rewrite",
        rationale=(
            "Self-claiming honesty ('四条诚实的边界'). Honest things "
            "don't announce themselves. State the boundaries; let the "
            "reader judge."
        ),
    ),
    KillEntry(
        literal="不要声称在跑",
        case_sensitive=False,
        kill_commit="2026-06-15 limits roadmap-list rewrite",
        rationale=(
            "Internal commit-message tone leaking onto a user surface. "
            "Use 'roadmap 上还没上线' for the reader."
        ),
    ),
    KillEntry(
        literal="请回来",
        case_sensitive=False,
        kill_commit="2026-06-15 limits lead rewrite",
        rationale=(
            "Reverse-marketing CTA inside the Limits section: 'come back "
            "when you need provenance'. Limits state boundaries; they do "
            "not invite return traffic."
        ),
    ),
    KillEntry(
        literal="飞轮",
        case_sensitive=False,
        kill_commit="2026-06-15 redesign-proposal rejection",
        rationale=(
            "'数据飞轮' / flywheel — SaaS growth-deck metaphor. A model-"
            "authored landing-rewrite proposal tried to introduce it while "
            "claiming to remove 装逼 metaphor (its own goal #1). Describe "
            "the mechanism (fail/pass → bene.db → next run's input), don't "
            "name it 飞轮."
        ),
    ),
    KillEntry(
        literal="硬核",
        case_sensitive=False,
        kill_commit="2026-06-15 redesign-proposal rejection",
        rationale=(
            "'硬核原语' / '硬核技术边界' — 装逼 intensifier with no payload. "
            "Same model-authored proposal that violated its own de-装逼 "
            "goal. State the concrete artifact; let the reader judge if "
            "it's 硬核."
        ),
    ),
]


def find_hits(text: str) -> list[tuple[KillEntry, int]]:
    """Return (entry, start_offset) for every literal hit, scanning the whole
    text. No regex, no allowlist — KILL_LIST is short-circuit."""
    hits: list[tuple[KillEntry, int]] = []
    for entry in KILL_LIST:
        haystack = text if entry.case_sensitive else text.lower()
        needle = entry.literal if entry.case_sensitive else entry.literal.lower()
        start = 0
        while True:
            idx = haystack.find(needle, start)
            if idx == -1:
                break
            hits.append((entry, idx))
            start = idx + 1
    return hits
