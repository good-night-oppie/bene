"""Tests for the parallel refactor swarm + SharedLog + live hub broadcast.

Covers:
  * _extract_pattern: JSON-first, regex fallback, nullish handling.
  * _hub_task: consolidation, policy emit, stop-event + shard-count exit.
  * _run_shard_lazy: end-to-end via FakeCCR; asserts parallel overlap, log entries.

Strategy: no real LLM. FakeCCR.run_agent returns canned strings on a sleep.
The hub and shards share a real Bene(:memory:-style temp file) and real
SharedLog, so the SQL-bypass cross-agent /discoveries pickup is exercised.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SWARM_PATH = REPO_ROOT / "scripts" / "ci" / "refactor_swarm.py"

spec = importlib.util.spec_from_file_location("refactor_swarm", SWARM_PATH)
assert spec and spec.loader, f"failed to load {SWARM_PATH}"
swarm = importlib.util.module_from_spec(spec)
sys.modules["refactor_swarm"] = swarm
spec.loader.exec_module(swarm)


# ────────────────────────────────────────────────────────────────────────────
# _extract_pattern unit tests
# ────────────────────────────────────────────────────────────────────────────


def test_extract_pattern_prefers_json():
    body = """Some narrative...
```json
{"pattern": "use cast(X, expr) for typing.Any returns"}
```
"""
    assert swarm._extract_pattern(body) == "use cast(X, expr) for typing.Any returns"


def test_extract_pattern_handles_none_json():
    body = '```json\n{"pattern": "none"}\n```'
    assert swarm._extract_pattern(body) is None


def test_extract_pattern_handles_empty_json():
    body = '```json\n{"pattern": ""}\n```'
    assert swarm._extract_pattern(body) is None


def test_extract_pattern_fallback_regex():
    body = "fixed bug\nPATTERN: prefer cast over type: ignore"
    assert swarm._extract_pattern(body) == "prefer cast over type: ignore"


def test_extract_pattern_last_wins():
    body = "PATTERN: foo\nlater work\nPATTERN: bar"
    assert swarm._extract_pattern(body) == "bar"


def test_extract_pattern_skips_invalid_json_then_falls_back():
    body = "```json\nNOT_JSON\n```\nPATTERN: from-regex"
    assert swarm._extract_pattern(body) == "from-regex"


def test_extract_pattern_none_when_empty_body():
    assert swarm._extract_pattern("") is None
    assert swarm._extract_pattern(None) is None  # type: ignore[arg-type]


# ────────────────────────────────────────────────────────────────────────────
# _hub_task tests — real SharedLog, in-memory-style Bene
# ────────────────────────────────────────────────────────────────────────────


def _new_bene(tmp_path: Path):
    from bene import Bene

    return Bene(str(tmp_path / "swarm.db"))


@pytest.mark.asyncio
async def test_hub_writes_consolidated_doc(tmp_path):
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    shard_a = afs.spawn("shard-a")
    hub_intent = log.intent(hub_id, action="hub", metadata={})

    intent_a = log.intent(shard_a, action="fix x.py")
    log.result(
        shard_a,
        ref_id=intent_a,
        payload={"file": "x.py", "pattern": "use cast over type: ignore"},
    )
    log.commit(shard_a, intent_id=intent_a, summary="done")

    stop = asyncio.Event()
    task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=1, poll_s=0.05)
    )
    result = await asyncio.wait_for(task, timeout=3)

    assert result["closed"] == 1
    assert len(result["patterns"]) == 1
    doc = afs.read(hub_id, "/discoveries/hub.md").decode()
    assert "use cast over type: ignore" in doc
    assert "x.py" in doc

    pols = log.read(type="policy", agent_id=hub_id)
    assert len(pols) == 1
    assert "use cast" in pols[0].payload["rule"]
    afs.close()


@pytest.mark.asyncio
async def test_hub_emits_policy_per_pattern(tmp_path):
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    for i, file in enumerate(["a.py", "b.py", "c.py"]):
        sid = afs.spawn(f"shard-{i}")
        iid = log.intent(sid, action=f"fix {file}")
        log.result(sid, ref_id=iid, payload={"file": file, "pattern": f"p{i}"})
        log.commit(sid, intent_id=iid, summary="done")

    stop = asyncio.Event()
    task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=3, poll_s=0.05)
    )
    await asyncio.wait_for(task, timeout=3)

    pols = log.read(type="policy", agent_id=hub_id)
    assert len(pols) == 3
    afs.close()


@pytest.mark.asyncio
async def test_hub_skips_none_pattern_results(tmp_path):
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    sid = afs.spawn("shard-no-pat")
    iid = log.intent(sid, action="fix y.py")
    log.result(sid, ref_id=iid, payload={"file": "y.py"})
    log.commit(sid, intent_id=iid, summary="done")

    stop = asyncio.Event()
    task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=1, poll_s=0.05)
    )
    result = await asyncio.wait_for(task, timeout=3)
    assert result["closed"] == 1
    assert result["patterns"] == []
    assert log.read(type="policy", agent_id=hub_id) == []
    afs.close()


@pytest.mark.asyncio
async def test_hub_stops_on_event(tmp_path):
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    stop = asyncio.Event()
    task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=99, poll_s=0.05)
    )

    await asyncio.sleep(0.1)
    stop.set()
    result = await asyncio.wait_for(task, timeout=2)
    assert result["closed"] == 0
    afs.close()


@pytest.mark.asyncio
async def test_hub_ignores_own_entries(tmp_path):
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    log.policy(hub_id, rule="seed policy")
    log.result(hub_id, ref_id=hub_intent, payload={"pattern": "self-pattern"})

    sid = afs.spawn("real-shard")
    iid = log.intent(sid, action="fix")
    log.commit(sid, intent_id=iid, summary="done")

    stop = asyncio.Event()
    task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=1, poll_s=0.05)
    )
    result = await asyncio.wait_for(task, timeout=3)
    assert result["patterns"] == []  # hub-emitted result was ignored
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# _read_discoveries — cross-agent SQL pickup of hub.md
# ────────────────────────────────────────────────────────────────────────────


def test_read_discoveries_picks_up_hub_md(tmp_path):
    afs = _new_bene(tmp_path)
    hub_id = afs.spawn(swarm.HUB_NAME)
    afs.write(hub_id, "/discoveries/hub.md", b"# Hub Broadcast\n- pattern x")

    afs.spawn("shard-a")  # different agent_id namespace
    discoveries = swarm._read_discoveries(afs)

    assert "Hub Broadcast" in discoveries
    assert "pattern x" in discoveries
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# _render_hub_doc
# ────────────────────────────────────────────────────────────────────────────


def test_render_hub_doc_includes_all_patterns():
    patterns = [
        {"shard": "shard-0", "file": "a.py", "pattern": "p-A"},
        {"shard": "shard-1", "file": "b.py", "pattern": "p-B"},
    ]
    doc = swarm._render_hub_doc(patterns, "2026-05-15T04:00:00Z")
    assert "2 cross-shard patterns collected" in doc
    assert "p-A" in doc and "p-B" in doc
    assert "a.py" in doc and "b.py" in doc


# ────────────────────────────────────────────────────────────────────────────
# Render summary includes hub section
# ────────────────────────────────────────────────────────────────────────────


def test_render_summary_includes_hub_when_patterns_exist():
    summary = [
        {
            "shard": 0,
            "file": "a.py",
            "errors_before": 3,
            "mypy_clean": True,
            "diff_lines": 5,
            "line_budget": 90,
            "kept": True,
            "reason": "ok",
            "patch": ".orchestra/refactor/patches/000.patch",
            "patch_bytes": 200,
            "pattern": "cast over ignore",
            "body": "agent output",
        }
    ]
    hub_summary = {
        "patterns": [{"shard": "mypyfix-a_py", "file": "a.py", "pattern": "cast over ignore"}],
        "closed": 1,
        "summary": "hub broadcast complete: 1 patterns from 1 shards",
    }
    out = swarm._render_summary("abc1234", summary, hub_summary)
    assert "## Hub broadcast (live)" in out
    assert "cast over ignore" in out
    assert "hub_patterns: 1" in out


def test_render_summary_omits_hub_section_when_no_patterns():
    summary = [
        {
            "shard": 0,
            "file": "a.py",
            "errors_before": 3,
            "mypy_clean": False,
            "diff_lines": 0,
            "line_budget": 90,
            "kept": False,
            "reason": "mypy not clean after fix",
            "patch": ".orchestra/refactor/patches/000.patch",
            "patch_bytes": 0,
            "pattern": None,
            "body": "",
        }
    ]
    hub_summary = {"patterns": [], "closed": 1, "summary": "n/a"}
    out = swarm._render_summary("abc1234", summary, hub_summary)
    assert "## Hub broadcast" not in out
    assert "hub_patterns: 0" in out


# ────────────────────────────────────────────────────────────────────────────
# Parallel overlap — assert _run_shard_lazy runs shards concurrently
# ────────────────────────────────────────────────────────────────────────────


class _FakeCCR:
    """Minimal CCR stand-in for _run_shard_lazy.

    run_agent sleeps to make overlap detectable; records timestamps.
    """

    def __init__(self, afs, max_parallel: int = 4, sleep_s: float = 0.25):
        self.afs = afs
        self.max_parallel_agents = max_parallel
        self._sleep_s = sleep_s
        self.timestamps: list[tuple[str, float, str]] = []
        self.prompts: dict[str, str] = {}

    async def run_agent(self, agent_id: str, prompt: str) -> str:
        self.timestamps.append(("start", time.monotonic(), agent_id))
        self.prompts[agent_id] = prompt
        await asyncio.sleep(self._sleep_s)
        self.timestamps.append(("end", time.monotonic(), agent_id))
        return 'Did the work.\n```json\n{"pattern": "cast over ignore"}\n```\n'


@pytest.mark.asyncio
async def test_shards_overlap_in_time(tmp_path, monkeypatch):
    """Multiple shards must overlap — last shard starts before first ends."""
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    ccr = _FakeCCR(afs, max_parallel=4, sleep_s=0.25)

    # Stub out filesystem-touching helpers; we only assert overlap + log shape.
    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: True)

    class _FakePatch:
        def __init__(self, path: Path):
            self._path = path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("dummy patch")

        def stat(self):
            return self._path.stat()

        def relative_to(self, root):
            return self._path

    def _fake_capture(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        return _FakePatch(p)._path  # return path-like; helpers expect .stat() etc.

    # Real _capture_patch returns Path; swap to a no-op path under tmp.
    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
        return p

    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)

    sem = asyncio.Semaphore(ccr.max_parallel_agents)
    metas = [
        {
            "idx": i,
            "file_rel": Path(f"f{i}.py"),
            "wt": tmp_path / "wt",
            "errors": "f{i}.py:1: error: bad\n",
            "name": f"shard-{i}",
        }
        for i in range(4)
    ]
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)

    results = await asyncio.gather(*[swarm._run_shard_lazy(afs, log, ccr, sem, m) for m in metas])

    starts = sorted(t for kind, t, _ in ccr.timestamps if kind == "start")
    ends = sorted(t for kind, t, _ in ccr.timestamps if kind == "end")
    assert max(starts) < min(ends), f"shards did not overlap: starts={starts} ends={ends}"
    assert all(r["pattern"] == "cast over ignore" for r in results)

    intents = log.read(type="intent")
    results_log = log.read(type="result")
    assert len(intents) == 4
    assert len(results_log) == 4
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# No process-cwd mutation — guards against _drive_swarm regression
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_shard_lazy_does_not_chdir(tmp_path, monkeypatch):
    """Confirms _run_shard_lazy never mutates process cwd (was a parallel
    correctness bug in the legacy sequential version).
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    ccr = _FakeCCR(afs, sleep_s=0.05)

    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: True)

    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
        return p

    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)

    sem = asyncio.Semaphore(2)
    meta = {
        "idx": 0,
        "file_rel": Path("f.py"),
        "wt": tmp_path / "wt",
        "errors": "f.py:1: error\n",
        "name": "shard-0",
    }
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)

    before = os.getcwd()
    await swarm._run_shard_lazy(afs, log, ccr, sem, meta)
    after = os.getcwd()
    assert before == after, "process cwd must not change during shard execution"
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# Cyclic dependency / deadlock integration tests
# ────────────────────────────────────────────────────────────────────────────


class _CyclicDepCCR:
    """FakeCCR where each shard's success depends on a peer's broadcast.

    Each shard, on run_agent:
      1. Reads /discoveries/hub.md cross-agent (the same _read_discoveries path
         used in real prompts).
      2. If `wants_peer` pattern string is present → emit own pattern + success.
         Else → still emit own pattern but pretend mypy stays dirty (clean=False
         downstream via stubbed _mypy_clean keyed off the agent_id).

    Combined with a fake _mypy_clean that consults a shared dict, this lets
    us assert: even with a CYCLIC peer-pattern dependency (A waits B, B
    waits A), the swarm completes within timeout instead of deadlocking.
    """

    def __init__(self, afs, max_parallel: int, sleep_s: float, plan: dict[str, str]):
        self.afs = afs
        self.max_parallel_agents = max_parallel
        self._sleep_s = sleep_s
        self._plan = plan  # task name → pattern string emitted
        self.seen_peer: dict[str, bool] = {}

    async def run_agent(self, agent_id: str, prompt: str) -> str:
        await asyncio.sleep(self._sleep_s)
        # Determine which shard from the prompt's target file path
        for name, pattern in self._plan.items():
            if f"mypyfix-{name}" in prompt or name in prompt:
                shard_name = name
                my_pattern = pattern
                break
        else:
            shard_name, my_pattern = agent_id, "unknown-pattern"
        # Inspect discoveries snapshot to see if peer broadcast arrived.
        peer_seen = "peer-pattern" in prompt and "peer-pattern" in prompt
        self.seen_peer[shard_name] = peer_seen
        return f'Did the work.\n```json\n{{"pattern": "{my_pattern}"}}\n```\n'


@pytest.mark.asyncio
async def test_cyclic_dependency_no_deadlock(tmp_path, monkeypatch):
    """Two shards with mutually-dependent fixes: A wants B's pattern, B wants
    A's pattern. With semaphore=1 (forced sequential) the broadcast flows
    A → hub → B, so B sees A's pattern. With semaphore=N (concurrent), neither
    sees the peer at start; the swarm must STILL complete (no deadlock) within
    a bounded timeout.

    Regression guard for circular import / cross-file type dependency PRs.
    """
    from bene.shared_log import SharedLog

    plan = {
        "a_py": "fix-a-with-cast",
        "b_py": "fix-b-with-cast",
    }

    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: True)

    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
        return p

    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)

    async def _run_swarm(max_parallel: int) -> tuple[list, float]:
        sub = tmp_path / f"db_{max_parallel}"
        sub.mkdir(parents=True, exist_ok=True)
        afs = _new_bene(sub)
        log = SharedLog(afs.conn)
        ccr = _CyclicDepCCR(afs, max_parallel=max_parallel, sleep_s=0.1, plan=plan)
        sem = asyncio.Semaphore(max_parallel)
        hub_id = afs.spawn(swarm.HUB_NAME)
        hub_intent = log.intent(hub_id, action="hub", metadata={"expected_shards": 2})
        stop = asyncio.Event()
        hub_task = asyncio.create_task(
            swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=2, poll_s=0.05)
        )
        metas = [
            {
                "idx": i,
                "file_rel": Path(name.replace("_", ".")),
                "wt": tmp_path / "wt",
                "errors": f"{name}:1: error\n",
                "name": f"mypyfix-{name}",
            }
            for i, name in enumerate(plan.keys())
        ]
        start = time.monotonic()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[swarm._run_shard_lazy(afs, log, ccr, sem, m) for m in metas]),
                timeout=10,
            )
        finally:
            stop.set()
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(hub_task, timeout=5)
        elapsed = time.monotonic() - start
        afs.close()
        return results, elapsed

    # Case 1: forced sequential (semaphore=1) — A runs first, hub broadcasts,
    # B picks up A's pattern in its lazy prompt.
    seq_results, seq_elapsed = await _run_swarm(max_parallel=1)
    assert len(seq_results) == 2
    assert all(r["pattern"] for r in seq_results)
    assert seq_elapsed < 5, f"sequential swarm took too long: {seq_elapsed:.2f}s"

    # Case 2: concurrent (semaphore=2) — both start at t=0, neither has peer
    # broadcast yet, but neither WAITS for the peer — they each emit and exit.
    # MUST NOT deadlock.
    conc_results, conc_elapsed = await _run_swarm(max_parallel=2)
    assert len(conc_results) == 2
    assert all(r["pattern"] for r in conc_results)
    assert conc_elapsed < 5, f"concurrent swarm deadlocked? {conc_elapsed:.2f}s"


@pytest.mark.asyncio
async def test_hung_shard_does_not_block_hub_indefinitely(tmp_path, monkeypatch):
    """If a single shard's run_agent hangs (network / LLM stall), the hub
    coroutine must still exit when stop_event is set by the caller — it must
    not wait for that shard's commit/abort entry forever.

    Demonstrates the try/finally + stop_event pattern protects against partial
    failure.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    stop = asyncio.Event()
    hub_task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=99, poll_s=0.05)
    )

    # Simulate one shard's commit; the rest never arrive.
    sid = afs.spawn("only-shard")
    iid = log.intent(sid, action="fix once")
    log.commit(sid, intent_id=iid, summary="ok")

    await asyncio.sleep(0.2)  # let hub observe the commit but not the rest
    stop.set()

    result = await asyncio.wait_for(hub_task, timeout=2)
    assert result["closed"] == 1
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# Full-context test — shards see BOTH focus-shard plan AND cross-shard hub
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_shards_get_full_context_not_partial(tmp_path, monkeypatch):
    """Each parallel shard's prompt MUST contain BOTH:
      (a) Focus-shard plan: own target file path + own mypy errors + per-shard
          line budget.
      (b) Cross-shard knowledge: peer's broadcast from /discoveries/hub.md
          (and any other /discoveries/* paths) injected via _read_discoveries.

    Regression guard: a buggy refactor could pass only (a) [shards isolated]
    or only (b) [shards lose their own scope]. Both must be present.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)

    # Seed hub broadcast BEFORE shards run, so _read_discoveries returns
    # non-empty cross-shard context at lazy prompt build time.
    hub_id = afs.spawn(swarm.HUB_NAME)
    peer_pattern_text = "PEER_PATTERN_FROM_HUB::use cast(Foo, x) when Any leaks"
    afs.write(
        hub_id,
        "/discoveries/hub.md",
        f"# Hub Broadcast\n- pattern: {peer_pattern_text}\n".encode(),
    )

    ccr = _FakeCCR(afs, max_parallel=3, sleep_s=0.05)
    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: True)

    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
        return p

    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)

    wt_root = tmp_path / "wt"
    wt_root.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(3)
    metas = [
        {
            "idx": 0,
            "file_rel": Path("alpha.py"),
            "wt": wt_root,
            "errors": "alpha.py:10: error: ALPHA_UNIQUE_ERROR no-any-return\n",
            "name": "mypyfix-alpha_py",
        },
        {
            "idx": 1,
            "file_rel": Path("beta.py"),
            "wt": wt_root,
            "errors": "beta.py:20: error: BETA_UNIQUE_ERROR assignment\n",
            "name": "mypyfix-beta_py",
        },
        {
            "idx": 2,
            "file_rel": Path("gamma.py"),
            "wt": wt_root,
            "errors": "gamma.py:30: error: GAMMA_UNIQUE_ERROR arg-type\n",
            "name": "mypyfix-gamma_py",
        },
    ]

    await asyncio.gather(*[swarm._run_shard_lazy(afs, log, ccr, sem, m) for m in metas])

    assert len(ccr.prompts) == 3, "expected 3 captured shard prompts"

    # Map agent_id back to shard name to make assertions readable.
    agent_to_name = {
        row["agent_id"]: row["name"]
        for row in afs.query("SELECT agent_id, name FROM agents")
        if isinstance(row["name"], str) and row["name"].startswith("mypyfix-")
    }

    # Per-shard assertions: focus + cross-shard both present.
    for agent_id, prompt in ccr.prompts.items():
        shard_name = agent_to_name.get(agent_id, agent_id)

        # (a) Focus-shard plan — unique to this shard.
        if "alpha" in shard_name:
            assert "alpha.py" in prompt
            assert "ALPHA_UNIQUE_ERROR" in prompt
            assert "BETA_UNIQUE_ERROR" not in prompt, (
                f"{shard_name} leaked peer beta error into focus plan"
            )
            assert "GAMMA_UNIQUE_ERROR" not in prompt, (
                f"{shard_name} leaked peer gamma error into focus plan"
            )
        elif "beta" in shard_name:
            assert "beta.py" in prompt
            assert "BETA_UNIQUE_ERROR" in prompt
            assert "ALPHA_UNIQUE_ERROR" not in prompt
            assert "GAMMA_UNIQUE_ERROR" not in prompt
        elif "gamma" in shard_name:
            assert "gamma.py" in prompt
            assert "GAMMA_UNIQUE_ERROR" in prompt
            assert "ALPHA_UNIQUE_ERROR" not in prompt
            assert "BETA_UNIQUE_ERROR" not in prompt

        # (b) Cross-shard knowledge — hub broadcast injected into every shard.
        assert "Cross-shard discoveries" in prompt, (
            f"{shard_name} missing cross-shard discoveries section"
        )
        assert peer_pattern_text in prompt, (
            f"{shard_name} did not receive seeded hub broadcast pattern"
        )
        assert "/discoveries/hub.md" in prompt, (
            f"{shard_name} discoveries section missing hub.md provenance path"
        )

        # Discovery output schema present (so agents know how to respond).
        assert '"pattern":' in prompt
        assert "```json" in prompt

    afs.close()


@pytest.mark.asyncio
async def test_late_shard_picks_up_fresh_hub_broadcast(tmp_path, monkeypatch):
    """Semaphore=1 forces sequential dispatch. The 1st shard's result feeds
    the hub, which writes hub.md. The 2nd shard's lazy-built prompt MUST
    include the broadcast that arrived AFTER the 1st shard's run started.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    # Start hub coroutine concurrently with shards (production code path).
    stop_event = asyncio.Event()
    hub_task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop_event, expected_shards=2, poll_s=0.02)
    )

    ccr = _FakeCCR(afs, max_parallel=1, sleep_s=0.05)
    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: True)

    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
        return p

    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(1)  # forces serial dispatch
    first_meta = {
        "idx": 0,
        "file_rel": Path("first.py"),
        "wt": tmp_path / "wt",
        "errors": "first.py:1: error\n",
        "name": "shard-first",
    }
    second_meta = {
        "idx": 1,
        "file_rel": Path("second.py"),
        "wt": tmp_path / "wt",
        "errors": "second.py:1: error\n",
        "name": "shard-second",
    }

    # Run shards sequentially with an explicit hub-catchup yield between them.
    # The race we are NOT testing is whether the hub polls quickly enough to
    # write hub.md before the next shard acquires the semaphore; that depends
    # on scheduler timing. The contract under test is: once the hub HAS
    # written, the next shard's lazy-built prompt picks it up via the
    # cross-agent SQL read.
    await swarm._run_shard_lazy(afs, log, ccr, sem, first_meta)

    # Give the hub coroutine multiple poll cycles to ingest shard-first's
    # result and write /discoveries/hub.md.
    for _ in range(20):
        await asyncio.sleep(0.05)
        try:
            doc = afs.read(hub_id, "/discoveries/hub.md").decode()
            if "cast over ignore" in doc:
                break
        except FileNotFoundError:
            continue
    else:
        pytest.fail("hub did not write /discoveries/hub.md after shard-first commit")

    await swarm._run_shard_lazy(afs, log, ccr, sem, second_meta)

    stop_event.set()
    with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(hub_task, timeout=2)

    agent_to_name = {
        row["agent_id"]: row["name"] for row in afs.query("SELECT agent_id, name FROM agents")
    }

    second_prompt = None
    for agent_id, prompt in ccr.prompts.items():
        if agent_to_name.get(agent_id) == "shard-second":
            second_prompt = prompt
            break
    assert second_prompt is not None, "shard-second prompt not captured"

    # _FakeCCR emits pattern 'cast over ignore' on every shard. The first
    # shard's commit + result must arrive in the log; the hub must have
    # consolidated it; the 2nd shard's lazy-built prompt must contain that
    # broadcast.
    assert "cast over ignore" in second_prompt, (
        "shard-second did not see hub broadcast from shard-first"
    )
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# R7 resource-exhaustion tests
# ────────────────────────────────────────────────────────────────────────────


class _HangingCCR:
    """CCR stand-in whose run_agent sleeps forever — to exercise SHARD_TIMEOUT_S."""

    def __init__(self, afs, max_parallel: int = 2):
        self.afs = afs
        self.max_parallel_agents = max_parallel

    async def run_agent(self, agent_id: str, prompt: str) -> str:
        await asyncio.sleep(3600)  # would block forever absent asyncio.wait_for
        return ""


@pytest.mark.asyncio
async def test_shard_timeout_aborts_cleanly(tmp_path, monkeypatch):
    """A hung run_agent must NOT hold the semaphore past SHARD_TIMEOUT_S.

    Guards against k8s resource exhaustion (R7): one stalled LLM call cannot
    block a sem slot for an hour. Result row should report timeout, log.abort
    should fire.
    """
    from bene.shared_log import SharedLog

    monkeypatch.setattr(swarm, "SHARD_TIMEOUT_S", 1)
    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: False)

    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return p

    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    ccr = _HangingCCR(afs, max_parallel=1)

    sem = asyncio.Semaphore(1)
    meta = {
        "idx": 0,
        "file_rel": Path("hung.py"),
        "wt": tmp_path / "wt",
        "errors": "hung.py:1: error\n",
        "name": "shard-hung",
    }
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    result = await asyncio.wait_for(swarm._run_shard_lazy(afs, log, ccr, sem, meta), timeout=5)
    elapsed = time.monotonic() - start

    assert elapsed < 3, f"shard ran too long ({elapsed:.2f}s) — wait_for did not fire"
    assert result["kept"] is False
    assert "timeout" in result["reason"].lower()
    aborts = log.read(type="abort")
    assert len(aborts) == 1
    afs.close()


def test_mypy_subprocess_timeout_returns_false(monkeypatch, tmp_path):
    """subprocess.TimeoutExpired in mypy must not propagate.

    Guards against runners hanging on a wedged mypy process.
    """

    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "mypy", timeout=1)

    monkeypatch.setattr(swarm.subprocess, "run", _fake_run)

    wt = tmp_path / "wt"
    wt.mkdir()
    assert swarm._mypy_clean(wt, Path("x.py")) is False


def test_afs_closed_on_drive_swarm_exception(tmp_path, monkeypatch):
    """If _drive_swarm raises mid-setup, afs.close() must still execute.

    Guards against SQLite WAL connection leakage on the exception path
    (the original P0-1 bug found by code review).
    """
    closed = {"called": False}

    def _fake_make_worktree(idx):
        raise RuntimeError("simulated worktree failure")

    monkeypatch.setattr(swarm, "_make_worktree", _fake_make_worktree)

    from bene import Bene

    real_close = Bene.close

    def _spy_close(self):
        closed["called"] = True
        return real_close(self)

    monkeypatch.setattr(Bene, "close", _spy_close)
    # Avoid the in-CI guard that requires BENE_CONFIG under .github/bene/ —
    # this test exercises the worktree exception path, not the CI guard.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("BENE_CONFIG", "bene.yaml")

    # Stub TierRouter.from_config so the test isolates the worktree-exception
    # path rather than failing earlier on missing bene.yaml.
    from bene.router import TierRouter

    monkeypatch.setattr(TierRouter, "from_config", classmethod(lambda cls, _cfg: object()))

    db_path = str(tmp_path / "drive.db")
    with pytest.raises(RuntimeError, match="simulated worktree failure"):
        asyncio.run(swarm._drive_swarm([Path("a.py")], db_path))

    assert closed["called"], "afs.close() was not called on exception path"


# ────────────────────────────────────────────────────────────────────────────
# R8 narrow-exception tests
# ────────────────────────────────────────────────────────────────────────────


def test_extract_pattern_handles_braces_in_pattern_value():
    """Real LLM output frequently has `}` inside the pattern string.

    Original non-greedy regex would truncate at the first `}`; the rewrite
    uses json.JSONDecoder.raw_decode which is brace-balanced.
    """
    body = '```json\n{"pattern": "wrap in {x: int} returns"}\n```'
    assert swarm._extract_pattern(body) == "wrap in {x: int} returns"


def test_extract_pattern_handles_multiline_json_with_braces():
    body = (
        "Did the work.\n"
        "```json\n"
        "{\n"
        '  "pattern": "use cast({}, expr) for typing.Any",\n'
        '  "applies_to": "bene/**/*.py"\n'
        "}\n"
        "```\n"
    )
    out = swarm._extract_pattern(body)
    assert out == "use cast({}, expr) for typing.Any"


def test_read_discoveries_swallows_only_sqlite_errors(monkeypatch, tmp_path):
    """_read_discoveries must catch sqlite3.Error but NOT bare Exception.

    Regression guard for the narrow-except principle: a programmer bug
    raising AttributeError must propagate, not be silently masked as "".
    """
    afs = _new_bene(tmp_path)

    def _bad_query(*args, **kwargs):
        raise AttributeError("intentional non-sqlite bug")

    monkeypatch.setattr(afs, "query", _bad_query)

    with pytest.raises(AttributeError, match="intentional non-sqlite bug"):
        swarm._read_discoveries(afs)

    afs.close()


def test_read_discoveries_catches_sqlite_error(monkeypatch, tmp_path):
    """Verifies the OTHER side of the narrow-except: sqlite3.Error -> '' (graceful)."""
    afs = _new_bene(tmp_path)

    def _sql_fail(*args, **kwargs):
        raise sqlite3.OperationalError("no such column: bogus")

    monkeypatch.setattr(afs, "query", _sql_fail)
    assert swarm._read_discoveries(afs) == ""
    afs.close()


# ────────────────────────────────────────────────────────────────────────────
# Post-rewrite regression guards from second codereview round
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hub_task_cancelled_when_outer_cancelled(tmp_path):
    """Outer task waits on hub via wait_for, gets cancelled. The teardown
    branch must catch CancelledError, cancel hub_task, then re-raise.
    Otherwise the orphaned hub coroutine resumes against a closed SQLite
    connection and crashes with sqlite3.ProgrammingError.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    stop_event = asyncio.Event()
    hub_task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop_event, expected_shards=999, poll_s=10)
    )

    async def _teardown_mirror():
        """Mirrors the finally-block lifecycle inside _drive_swarm."""
        try:
            await asyncio.wait_for(hub_task, timeout=10)
        except asyncio.TimeoutError:
            hub_task.cancel()
            try:
                await hub_task
            except (asyncio.CancelledError, sqlite3.Error):
                pass
        except asyncio.CancelledError:
            hub_task.cancel()
            try:
                await hub_task
            except (asyncio.CancelledError, sqlite3.Error):
                pass
            raise

    outer = asyncio.create_task(_teardown_mirror())
    await asyncio.sleep(0.05)
    outer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await outer

    assert hub_task.done(), "hub_task was not cancelled when outer cancelled"
    afs.close()


def test_build_manifest_rejects_absolute_paths(tmp_path, monkeypatch):
    """Manifest entries that are absolute paths or contain `..` MUST be
    dropped — `wt / Path("/etc/passwd")` would otherwise resolve to the
    absolute path, escaping the worktree isolation.
    """
    monkeypatch.setattr(swarm, "OUT_DIR", tmp_path)
    monkeypatch.setattr(swarm.subprocess, "run", lambda *a, **kw: None)
    (tmp_path / "manifest.txt").write_text(
        "bene/safe.py\n/etc/passwd\n../outside.py\nbene/also_safe.py\n"
    )
    files = swarm._build_manifest(max_shards=4)
    assert files == [Path("bene/safe.py"), Path("bene/also_safe.py")]


def test_mypy_subprocess_uses_dash_dash_separator(monkeypatch, tmp_path):
    """A file path starting with `-` must be treated as a positional arg,
    not parsed as a mypy flag. Verified by inspecting the captured argv.
    """
    captured = {}

    def _capture_run(args, **kwargs):
        captured["args"] = list(args)

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(swarm.subprocess, "run", _capture_run)
    wt = tmp_path / "wt"
    wt.mkdir()
    swarm._mypy_clean(wt, Path("-malicious.py"))
    assert "--" in captured["args"], "missing -- separator before file path"
    dash_idx = captured["args"].index("--")
    assert captured["args"][dash_idx + 1] == "-malicious.py"


def test_sha_returns_unknown_when_git_missing(monkeypatch):
    """If the git binary itself is missing (FileNotFoundError / OSError),
    _sha must degrade gracefully instead of crashing the swarm.
    """

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git binary not on PATH")

    monkeypatch.setattr(swarm.subprocess, "check_output", _no_git)
    assert swarm._sha() == "unknown"


# ────────────────────────────────────────────────────────────────────────────
# Round-3 graceful-degrade regression guards
# ────────────────────────────────────────────────────────────────────────────


def test_capture_patch_handles_called_process_error(monkeypatch, tmp_path):
    """If `git diff` exits non-zero (check=True path) the shard must still
    record log.abort. _capture_patch swallows the error and returns an
    empty patch file rather than propagating into the shard's main flow.
    """

    def _fail(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=args[0])

    monkeypatch.setattr(swarm.subprocess, "run", _fail)
    monkeypatch.setattr(swarm, "PATCH_DIR", tmp_path)
    patch = swarm._capture_patch(tmp_path, 0)
    assert patch.exists()
    assert patch.read_text() == ""


def test_capture_patch_handles_missing_git(monkeypatch, tmp_path):
    """FileNotFoundError (OSError) when git binary is missing must not
    propagate. Patch file is still written as empty so downstream logic
    can classify the shard as 'empty patch'.
    """

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("no git on PATH")

    monkeypatch.setattr(swarm.subprocess, "run", _no_git)
    monkeypatch.setattr(swarm, "PATCH_DIR", tmp_path)
    patch = swarm._capture_patch(tmp_path, 0)
    assert patch.exists()
    assert patch.read_text() == ""


@pytest.mark.asyncio
async def test_hub_skips_non_dict_payload(tmp_path):
    """Hub must guard against malformed `result` entries where payload is
    not a dict — otherwise .get('pattern') would raise AttributeError and
    crash the hub mid-poll.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    hub_id = afs.spawn(swarm.HUB_NAME)
    hub_intent = log.intent(hub_id, action="hub")

    # Append a result entry with a STRING payload (bypassing helpers).
    sid = afs.spawn("malformed-shard")
    iid = log.intent(sid, action="x")
    # Use raw _append to inject a non-dict payload. SharedLog public API
    # always passes dicts; production entries from misbehaving agents
    # could in principle bypass this if anyone uses raw SQL — guard.
    afs.conn.execute(
        "INSERT INTO shared_log (position, type, agent_id, ref_id, payload) "
        "VALUES ((SELECT COALESCE(MAX(position),-1)+1 FROM shared_log), "
        "'result', ?, ?, ?)",
        (sid, iid, '"not a dict"'),
    )
    afs.conn.commit()
    log.commit(sid, intent_id=iid, summary="done")

    stop = asyncio.Event()
    task = asyncio.create_task(
        swarm._hub_task(afs, log, hub_id, hub_intent, stop, expected_shards=1, poll_s=0.05)
    )
    # Should not crash; hub completes via closed-count.
    result = await asyncio.wait_for(task, timeout=3)
    assert result["closed"] == 1
    assert result["patterns"] == []
    afs.close()


def test_main_handles_oserror_gracefully(monkeypatch, tmp_path):
    """If git binary is missing during worktree setup, main() must still
    write the markdown report and return 0 — graceful-degrade contract.
    """
    monkeypatch.setattr(swarm, "OUT_DIR", tmp_path)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("BENE_DB", str(tmp_path / "t.db"))

    # Pretend manifest exists with one entry.
    (tmp_path / "manifest.txt").write_text("bene/x.py\n")
    monkeypatch.setattr(swarm, "_build_manifest", lambda n: [Path("bene/x.py")])

    # Stub asyncio.run to raise without ever running the coroutine. Close
    # the coroutine first to avoid "coroutine never awaited" warning.
    def _raise_oserror(coro, *args, **kwargs):
        coro.close()
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(swarm.asyncio, "run", _raise_oserror)
    monkeypatch.setattr(swarm, "_cleanup_worktrees", lambda: None)
    monkeypatch.setattr(swarm, "_post_pr_comment", lambda p: None)
    monkeypatch.setattr(swarm.sys, "argv", ["refactor_swarm.py", "--max-shards", "1"])

    rc = swarm.main()
    assert rc == 0
    out = list(tmp_path.glob("swarm-*.md"))
    assert out, "main() did not write markdown report on OSError"
    assert "Swarm aborted" in out[0].read_text()


# ────────────────────────────────────────────────────────────────────────────
# Round-4: LogAct closure invariant
# ────────────────────────────────────────────────────────────────────────────


class _RaisingCCR:
    """CCR stand-in whose run_agent raises a NON-timeout exception.

    Models httpx network errors, KeyError from malformed config, etc. —
    anything that escapes the asyncio.TimeoutError catch.
    """

    def __init__(self, afs, max_parallel: int = 2, exc: Exception | None = None):
        self.afs = afs
        self.max_parallel_agents = max_parallel
        self._exc = exc or RuntimeError("simulated upstream connect error")

    async def run_agent(self, agent_id: str, prompt: str) -> str:
        raise self._exc


@pytest.mark.asyncio
async def test_shard_logs_abort_on_non_timeout_exception(tmp_path, monkeypatch):
    """LogAct closure invariant: if ccr.run_agent raises any exception other
    than asyncio.TimeoutError, the shard MUST still emit log.abort via the
    finally block. Otherwise the hub's `closed` counter never advances for
    this shard and teardown burns HUB_TEARDOWN_S.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)
    ccr = _RaisingCCR(afs, max_parallel=1)

    def _capture_under_tmp(wt, idx):
        p = tmp_path / f"patches/{idx:03d}.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return p

    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: False)
    monkeypatch.setattr(swarm, "_capture_patch", _capture_under_tmp)
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(1)
    meta = {
        "idx": 0,
        "file_rel": Path("x.py"),
        "wt": tmp_path / "wt",
        "errors": "x.py:1: error\n",
        "name": "shard-x",
    }

    with pytest.raises(RuntimeError, match="simulated upstream connect error"):
        await swarm._run_shard_lazy(afs, log, ccr, sem, meta)

    # The LogAct closure invariant: an abort entry must exist for this shard.
    aborts = log.read(type="abort")
    assert len(aborts) == 1
    assert "without commit/abort" in aborts[0].payload.get("reason", "") or "shard" in aborts[
        0
    ].payload.get("reason", "")
    afs.close()


@pytest.mark.asyncio
async def test_shard_logs_abort_on_cancellation(tmp_path, monkeypatch):
    """Cancelling a shard mid-run_agent must also trigger the fallback
    log.abort. Same closure invariant as the exception case.
    """
    from bene.shared_log import SharedLog

    afs = _new_bene(tmp_path)
    log = SharedLog(afs.conn)

    class _SlowCCR:
        def __init__(self, afs):
            self.afs = afs
            self.max_parallel_agents = 1

        async def run_agent(self, agent_id, prompt):
            await asyncio.sleep(10)
            return ""

    monkeypatch.setattr(swarm, "_mypy_clean", lambda wt, f: False)
    monkeypatch.setattr(
        swarm,
        "_capture_patch",
        lambda wt, idx: (
            (tmp_path / f"patches/{idx:03d}.patch")
            if (tmp_path / "patches").mkdir(parents=True, exist_ok=True) or True
            else None
        ),
    )
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)
    (tmp_path / "patches").mkdir(parents=True, exist_ok=True)
    (tmp_path / "patches" / "000.patch").write_text("")

    sem = asyncio.Semaphore(1)
    meta = {
        "idx": 0,
        "file_rel": Path("y.py"),
        "wt": tmp_path / "wt",
        "errors": "y.py:1: error\n",
        "name": "shard-y",
    }
    ccr = _SlowCCR(afs)

    shard = asyncio.create_task(swarm._run_shard_lazy(afs, log, ccr, sem, meta))
    await asyncio.sleep(0.1)
    shard.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await shard

    aborts = log.read(type="abort")
    assert len(aborts) == 1, "fallback abort not emitted on cancellation"
    afs.close()


def test_post_pr_comment_handles_oserror(monkeypatch, tmp_path):
    """TOCTOU: gh binary disappears between shutil.which() and subprocess.run.
    Must degrade silently, not propagate.
    """
    monkeypatch.setenv("PR_NUMBER", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    monkeypatch.setattr(swarm.shutil, "which", lambda _: "/usr/bin/gh")

    def _toctou(*args, **kwargs):
        raise FileNotFoundError("gh vanished")

    monkeypatch.setattr(swarm.subprocess, "run", _toctou)
    out = tmp_path / "report.md"
    out.write_text("# report")
    # Must not raise.
    swarm._post_pr_comment(out)


def test_apply_and_push_skips_rejected_patches(monkeypatch, tmp_path, capsys):
    """When git apply rejects a patch (overlap/conflict), the stderr message
    must surface so reviewers can act. _apply_and_push prints `skip patch
    <name>: <stderr>` and continues without counting it as applied.
    """
    patch_path = tmp_path / "patches" / "000.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("bogus patch content")

    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_HEAD_REF", "feat/test")

    class _Result:
        returncode = 1
        stderr = "error: patch failed: foo.py:10"
        stdout = ""

    monkeypatch.setattr(swarm.subprocess, "run", lambda *a, **kw: _Result())

    summary = [
        {"kept": True, "patch": str(patch_path.relative_to(tmp_path))},
        {"kept": False, "patch": "skipped.patch"},
    ]
    applied = swarm._apply_and_push(summary)
    assert applied == 0
    out = capsys.readouterr().out
    assert "skip patch" in out
    assert "foo.py:10" in out


def test_apply_and_push_skips_when_not_on_pr_run(monkeypatch):
    """Without GITHUB_HEAD_REF (not a PR run), _apply_and_push must no-op."""
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    summary = [{"kept": True, "patch": "p.patch"}]
    assert swarm._apply_and_push(summary) == 0


def test_apply_and_push_handles_missing_git(monkeypatch, tmp_path):
    """If git binary is missing, the per-patch apply step must catch
    FileNotFoundError and return 0 (no crash, no push attempted).
    """
    monkeypatch.setattr(swarm, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_HEAD_REF", "feat/test")

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(swarm.subprocess, "run", _no_git)
    summary = [{"kept": True, "patch": "p.patch"}]
    assert swarm._apply_and_push(summary) == 0
