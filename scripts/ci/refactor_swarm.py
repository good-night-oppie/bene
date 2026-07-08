#!/usr/bin/env python3
"""BENE refactor swarm — parallel mypy-fix agents with LogAct hub broadcast.

External contract (callers / CI workflow depend on these — do not break):

  CLI flags:   --max-shards N, --apply
  Env vars:    BENE_CONFIG, BENE_DB, PR_NUMBER, GITHUB_TOKEN, GITHUB_ACTIONS,
               BENE_MAX_LINES_PER_ERROR, BENE_MAX_TOTAL_LINES, BENE_MAX_TURNS,
               BENE_HUB_POLL_S, BENE_HUB_TEARDOWN_S, BENE_SHARD_TIMEOUT_S,
               BENE_MYPY_TIMEOUT_S, BENE_GIT_TIMEOUT_S, BENE_GH_TIMEOUT_S,
               BENE_MANIFEST_TIMEOUT_S
  Outputs:     .orchestra/refactor/swarm-{sha}.md
               .orchestra/refactor/swarm-{sha}.json
               .orchestra/refactor/refactor.db (audit / LogAct)
               .orchestra/refactor/patches/{idx:03d}.patch
  Manifest:    scripts/ci/manifest_from_mypy.sh
  Hub agent:   stable name "swarm-hub" (cross-run aggregator)

Architecture:

  * Per-shard git worktree (FS isolation; pre-created sequentially up front).
  * asyncio.gather(*shards) bounded by an explicit Semaphore — true parallel.
  * Lazy prompt build at semaphore-acquire so late-queued shards pick up
    fresh hub broadcasts via _read_discoveries cross-agent SQL read.
  * LogAct (Balakrishnan et al. 2026, arXiv:2604.07988 — implemented at
    bene/shared_log.py): each shard records intent/result/commit/abort;
    the hub records one policy entry per cross-shard pattern.
  * Hub coroutine: polls SharedLog, consolidates patterns into
    /discoveries/hub.md (under stable agent_id "swarm-hub"), broadcasts
    via policy entries, exits on stop_event OR when all expected shards
    close (commit+abort tally).
  * Discovery extraction: json.JSONDecoder.raw_decode inside fenced JSON
    blocks; brace-balanced (tolerates `}` inside string values such as
    {"pattern": "wrap in {x: int}"}). Regex fallback for legacy PATTERN:
    emissions.

Hard invariants (enforced by the test suite at tests/test_refactor_swarm.py):

  I1  No `except Exception` or `contextlib.suppress(Exception)` anywhere.
      Only narrow catches: sqlite3.Error, OSError, asyncio.TimeoutError,
      asyncio.CancelledError, json.JSONDecodeError, subprocess.TimeoutExpired,
      subprocess.CalledProcessError.
  I2  Every subprocess invocation carries a finite timeout=.
  I3  Every awaited ccr.run_agent is wrapped in asyncio.wait_for.
  I4  Bene().close() runs in try/finally — never leaked.
  I5  Hub task cancelled before afs.close() under any outer cancellation —
      no orphaned coroutine touches a closed SQLite connection.
  I6  No os.chdir — parallel-safe; absolute paths flow to subprocess and
      agent prompts.
  I7  Subprocess args separated by `--` whenever a filename could begin
      with `-` (mypy flag injection).
  I8  Manifest entries that are absolute or contain `..` are dropped at
      ingest (worktree-escape protection).

Graceful degrade is the contract: missing git binary, missing bene package,
missing API key, mypy hang, network stall — none of these crash the swarm.
Each is logged + degrades to an explanatory markdown report and exit 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Paths & environment-driven constants ────────────────────────────────


REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / ".orchestra" / "refactor"
PATCH_DIR = OUT_DIR / "patches"
WT_DIR = OUT_DIR / "worktrees"

MAX_LINES_PER_ERROR = int(os.environ.get("BENE_MAX_LINES_PER_ERROR", "30"))
MAX_TOTAL_LINES = int(os.environ.get("BENE_MAX_TOTAL_LINES", "300"))
MAX_TURNS = int(os.environ.get("BENE_MAX_TURNS", "3"))

HUB_POLL_S = float(os.environ.get("BENE_HUB_POLL_S", "2"))
HUB_TEARDOWN_S = int(os.environ.get("BENE_HUB_TEARDOWN_S", "10"))
SHARD_TIMEOUT_S = int(os.environ.get("BENE_SHARD_TIMEOUT_S", "1800"))
MYPY_TIMEOUT_S = int(os.environ.get("BENE_MYPY_TIMEOUT_S", "300"))
GIT_TIMEOUT_S = int(os.environ.get("BENE_GIT_TIMEOUT_S", "60"))
GH_TIMEOUT_S = int(os.environ.get("BENE_GH_TIMEOUT_S", "60"))
MANIFEST_TIMEOUT_S = int(os.environ.get("BENE_MANIFEST_TIMEOUT_S", "300"))

HUB_NAME = "swarm-hub"
HUB_DOC_PATH = "/discoveries/hub.md"

# Discovery extraction. Prefer structured JSON inside ```json fences; fall
# back to PATTERN: regex for backward compat with older shard prompts.
_JSON_FENCE_RE = re.compile(r"```json\s*\n?(.*?)```", re.DOTALL)
_PATTERN_RE = re.compile(r"^\s*PATTERN\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_NULLISH = frozenset({"", "none", "null", "n/a"})


# ── Pure helpers ────────────────────────────────────────────────────────


def _sha() -> str:
    """Short git sha of HEAD. Returns 'unknown' when git is unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            timeout=GIT_TIMEOUT_S,
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return "unknown"


def _errors_for(file_path: Path) -> str:
    raw = (OUT_DIR / "mypy.raw").read_text(errors="ignore")
    needle = f"{file_path}:"
    return "\n".join(line for line in raw.splitlines() if line.startswith(needle))


def _diff_line_count(patch_path: Path) -> int:
    if not patch_path.exists():
        return 0
    return sum(
        1
        for line in patch_path.read_text(errors="ignore").splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not (line.startswith("+++") or line.startswith("---"))
    )


# ── Manifest ingest (path-traversal hardening at the boundary) ──────────


def _build_manifest(max_shards: int) -> list[Path]:
    """Run manifest_from_mypy.sh and parse rows.

    Drops absolute paths and `..` traversal — `wt / Path("/etc/passwd")`
    would otherwise resolve to the absolute path, escaping the worktree
    isolation that the swarm relies on for parallel safety.
    """
    script = REPO_ROOT / "scripts" / "ci" / "manifest_from_mypy.sh"
    subprocess.run(
        ["bash", str(script), str(max_shards)],
        check=True,
        cwd=REPO_ROOT,
        timeout=MANIFEST_TIMEOUT_S,
    )
    raw = (OUT_DIR / "manifest.txt").read_text().splitlines()
    files: list[Path] = []
    for entry in raw:
        candidate = entry.strip()
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_absolute() or ".." in path.parts:
            logger.warning("manifest entry rejected (non-relative): %s", candidate)
            continue
        files.append(path)
    return files


# ── Git worktree management ─────────────────────────────────────────────


def _git_worktree_remove(wt: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt)],
        cwd=REPO_ROOT,
        check=False,
        timeout=GIT_TIMEOUT_S,
    )


def _git_worktree_prune() -> None:
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=REPO_ROOT,
        check=False,
        timeout=GIT_TIMEOUT_S,
    )


def _make_worktree(shard_idx: int) -> Path:
    wt = WT_DIR / f"wt-{shard_idx}"
    if wt.exists():
        _git_worktree_remove(wt)
    _git_worktree_prune()
    WT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        timeout=GIT_TIMEOUT_S,
    )
    return wt


def _cleanup_worktrees() -> None:
    if not WT_DIR.exists():
        return
    for wt in WT_DIR.iterdir():
        _git_worktree_remove(wt)
    _git_worktree_prune()


def _capture_patch(wt: Path, shard_idx: int) -> Path:
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    patch = PATCH_DIR / f"{shard_idx:03d}.patch"
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=wt,
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        ).stdout
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
        # CalledProcessError from check=True if git diff exits non-zero;
        # OSError if git binary is missing. Either way, degrade to empty
        # diff so the shard can still complete log.abort cleanly.
        logger.warning("git diff failed for shard %d wt=%s: %s", shard_idx, wt, exc)
        diff = ""
    patch.write_text(diff)
    return patch


def _mypy_clean(wt: Path, file_rel: Path) -> bool:
    """Run mypy on a single file under the worktree.

    The `--` separator stops mypy from interpreting filenames that begin
    with `-` as command-line flags (subprocess arg injection hardening).
    """
    try:
        proc = subprocess.run(
            ["uv", "run", "mypy", "--ignore-missing-imports", "--", str(file_rel)],
            cwd=wt,
            capture_output=True,
            text=True,
            timeout=MYPY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logger.warning("mypy timed out (>%ds) for %s", MYPY_TIMEOUT_S, file_rel)
        return False
    return proc.returncode == 0


# ── Prompt + structured discovery extraction ────────────────────────────


def _build_prompt(target_abs: Path, errors: str, discoveries: str) -> str:
    n_errors = max(1, errors.count("\n") + (1 if errors else 0))
    line_budget = min(MAX_TOTAL_LINES, n_errors * MAX_LINES_PER_ERROR)
    return (
        "You are a Python type-fixing agent. Fix mypy errors in ONE file.\n\n"
        f"### Target file (absolute path):\n{target_abs}\n\n"
        f"### Mypy errors to address:\n```\n{errors}\n```\n\n"
        "### Cross-shard discoveries (read-only, from earlier agents + hub):\n"
        f"{discoveries or '(none yet)'}\n\n"
        "Rules:\n"
        "- Edit ONLY the target file. Do not modify other files.\n"
        "- Do NOT reformat the file. Do not change unrelated whitespace,\n"
        "  imports, quoting, or line wrapping. Touch only what the error\n"
        "  forces you to touch.\n"
        f"- Keep total diff under ~{line_budget} added/removed lines\n"
        f"  ({MAX_LINES_PER_ERROR} per error, hard cap {MAX_TOTAL_LINES}).\n"
        "  Patches above this budget are rejected at the verify gate.\n"
        "- Prefer minimal annotations / `cast` over runtime changes.\n"
        "- Run `uv run mypy --ignore-missing-imports <target>` to verify.\n"
        "- Stop as soon as mypy is clean for this file.\n\n"
        "### Output Discovery Format (REQUIRED)\n"
        "At the end of your final message, output a fenced JSON block:\n"
        "```json\n"
        '{"pattern": "<one short reusable type-fix idiom>", '
        '"applies_to": "<file glob or path>"}\n'
        "```\n"
        "If no reusable pattern was found, output exactly:\n"
        "```json\n"
        '{"pattern": "none"}\n'
        "```\n"
    )


def _extract_pattern(body: str) -> str | None:
    """Return a discovered pattern string, or None if absent / nullish.

    Strategy:
      1. For each fenced ```json … ``` block, use json.JSONDecoder.raw_decode
         to parse one balanced JSON value (brace-balanced; tolerates `}`
         inside string literals). Trailing text inside the block is ignored.
      2. If no JSON yielded a non-nullish "pattern", fall back to the
         PATTERN: line regex for legacy emissions.
    Last non-nullish wins (agents sometimes echo the pattern multiple times).
    """
    if not body:
        return None
    decoder = json.JSONDecoder()
    json_candidates: list[str] = []
    for block in _JSON_FENCE_RE.findall(body):
        text = block.strip()
        start = text.find("{")
        if start < 0:
            continue
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        pattern = data.get("pattern")
        if isinstance(pattern, str) and pattern.strip().lower() not in _NULLISH:
            json_candidates.append(pattern.strip())
    if json_candidates:
        return json_candidates[-1]
    for cand in reversed(_PATTERN_RE.findall(body)):
        if cand and cand.strip().lower() not in _NULLISH:
            return cand.strip()
    return None


# ── Cross-agent /discoveries SQL bypass ────────────────────────────────


def _read_discoveries(afs: Any) -> str:
    """Read all /discoveries/* files across agent namespaces.

    Bene VFS reads are per-agent_id by design. The hub writes under
    `swarm-hub` and shards run under their own agent_ids, so a direct
    VFS read won't see the hub broadcast. We pull rows via raw SQL and
    decompress through BlobStore.retrieve() to honour zstd compression.
    """
    try:
        rows = afs.query(
            "SELECT path, content_hash FROM files "
            "WHERE path LIKE '/discoveries/%' AND deleted = 0 "
            "ORDER BY created_at"
        )
    except sqlite3.Error as exc:
        logger.warning("_read_discoveries SQL failed: %s", exc)
        return ""
    chunks: list[str] = []
    for row in rows or []:
        try:
            raw = afs.blobs.retrieve(row["content_hash"])
        except (sqlite3.Error, OSError) as exc:
            logger.warning("blob retrieve failed for %s: %s", row.get("path"), exc)
            continue
        body = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else ""
        chunks.append(f"--- {row['path']} ---\n{body}")
    return "\n\n".join(chunks)


# ── Hub coroutine (LogAct policy broadcaster) ───────────────────────────


def _render_hub_doc(patterns: list[dict[str, Any]], swarm_started_at: str) -> str:
    lines = [
        f"# Hub Broadcast (live, swarm started {swarm_started_at})",
        f"_{len(patterns)} cross-shard patterns collected_",
        "",
    ]
    for i, pattern_meta in enumerate(patterns, 1):
        lines += [
            f"## Pattern {i} — from `{pattern_meta['shard']}`",
            f"- file: `{pattern_meta.get('file', '?')}`",
            f"- pattern: {pattern_meta['pattern']}",
            "",
        ]
    return "\n".join(lines)


async def _hub_task(
    afs: Any,
    log: Any,
    hub_id: str,
    hub_intent_id: int,
    stop_event: asyncio.Event,
    expected_shards: int,
    poll_s: float = HUB_POLL_S,
) -> dict[str, Any]:
    """Poll SharedLog, consolidate cross-shard patterns, broadcast.

    Exit conditions (whichever first):
      - stop_event set by the driver during teardown.
      - expected_shards `commit`+`abort` entries observed in the log.

    Cancellation: if the surrounding task is cancelled, asyncio propagates
    CancelledError into the awaited stop_event.wait — the coroutine exits
    via the normal raise path. The driver (`_drive_swarm`) is responsible
    for awaiting this task to completion before closing afs.
    """
    cursor = 0
    patterns: list[dict[str, Any]] = []
    closed = 0
    started_at = datetime.now(timezone.utc).isoformat()

    while not stop_event.is_set():
        try:
            entries = log.read(since_position=cursor, limit=100)
        except sqlite3.Error as exc:
            logger.warning("hub log.read failed: %s", exc)
            await _wait_or_stop(stop_event, poll_s)
            continue

        for entry in entries:
            cursor = max(cursor, entry.position + 1)
            if entry.agent_id == hub_id:
                continue  # ignore self
            if entry.type == "result":
                if not isinstance(entry.payload, dict):
                    logger.warning(
                        "hub skipped non-dict result payload from %s: %r",
                        entry.agent_id,
                        type(entry.payload).__name__,
                    )
                    continue
                pattern = entry.payload.get("pattern")
                if not pattern:
                    continue
                patterns.append(
                    {
                        "shard": entry.agent_id,
                        "file": entry.payload.get("file"),
                        "pattern": pattern,
                    }
                )
                _hub_publish(afs, log, hub_id, patterns, started_at, entry, pattern)
            elif entry.type in ("commit", "abort"):
                closed += 1

        if closed >= expected_shards:
            break
        await _wait_or_stop(stop_event, poll_s)

    summary = f"hub broadcast complete: {len(patterns)} patterns from {closed} shards"
    try:
        log.commit(agent_id=hub_id, intent_id=hub_intent_id, summary=summary)
    except sqlite3.Error as exc:
        logger.warning("hub final commit failed: %s", exc)
    return {"patterns": patterns, "closed": closed, "summary": summary}


async def _wait_or_stop(stop_event: asyncio.Event, poll_s: float) -> None:
    """Sleep up to `poll_s` seconds, but wake immediately if stop_event fires."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=poll_s)
    except asyncio.TimeoutError:
        pass


def _hub_publish(
    afs: Any,
    log: Any,
    hub_id: str,
    patterns: list[dict[str, Any]],
    started_at: str,
    source_entry: Any,
    pattern: str,
) -> None:
    """Write consolidated hub.md and emit a LogAct policy entry."""
    doc = _render_hub_doc(patterns, started_at).encode()
    try:
        afs.write(hub_id, HUB_DOC_PATH, doc)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("hub write %s failed: %s", HUB_DOC_PATH, exc)
    try:
        log.policy(
            agent_id=hub_id,
            rule=f"Cross-shard pattern: {pattern}",
            metadata={
                "source_shard": source_entry.agent_id,
                "file": source_entry.payload.get("file"),
            },
        )
    except sqlite3.Error as exc:
        logger.warning("hub log.policy failed: %s", exc)


# ── Shard runner (lazy prompt; timeout-aware) ───────────────────────────


def _classify_outcome(
    timed_out: bool,
    clean: bool,
    patch_bytes: int,
    diff_lines: int,
    line_budget: int,
) -> tuple[bool, str]:
    if timed_out:
        return False, f"timeout after {SHARD_TIMEOUT_S}s"
    if not clean:
        return False, "mypy not clean after fix"
    if patch_bytes == 0:
        return False, "empty patch"
    if diff_lines > line_budget:
        return False, f"diff {diff_lines} lines > budget {line_budget}"
    return True, "ok"


def _shard_outcome(
    *,
    idx: int,
    file_rel: Path,
    name: str,
    agent_id: str,
    body: str,
    pattern: str | None,
    clean: bool,
    patch: Path,
    diff_lines: int,
    n_errors: int,
    line_budget: int,
    kept: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "shard": idx,
        "file": str(file_rel),
        "agent": name,
        "agent_id": agent_id,
        "errors_before": n_errors,
        "mypy_clean": clean,
        "diff_lines": diff_lines,
        "line_budget": line_budget,
        "kept": kept,
        "reason": reason,
        "patch": str(patch.relative_to(REPO_ROOT)) if patch else "",
        "patch_bytes": patch.stat().st_size if patch and patch.exists() else 0,
        "pattern": pattern,
        "body": (body or "").strip()[:2000],
    }


def _shard_exception_row(idx: int, meta: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    return {
        "shard": idx,
        "file": str(meta["file_rel"]),
        "agent": meta["name"],
        "errors_before": 0,
        "mypy_clean": False,
        "diff_lines": 0,
        "line_budget": 0,
        "kept": False,
        "reason": f"shard exception: {type(exc).__name__}: {exc}",
        "patch": "",
        "patch_bytes": 0,
        "pattern": None,
        "body": "",
    }


async def _run_shard_lazy(
    afs: Any,
    log: Any,
    ccr: Any,
    sem: asyncio.Semaphore,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Run one shard. Prompt built AFTER semaphore acquires (live broadcast).

    LogAct closure invariant: once intent is recorded, the shard MUST emit
    a matching commit or abort before exiting — otherwise the hub's expected
    close-count never reaches expected_shards and teardown burns
    HUB_TEARDOWN_S of extra polling. The closure is guaranteed by a
    try/finally with a `closed` sentinel — finally writes log.abort if
    neither commit nor abort ran, no matter how the body exits (timeout,
    network error, CancelledError, anything).

    Behavior on timeout: log.abort, mypy_clean=False, reason="timeout …".
    Behavior on agent crash: log.abort fired via finally (reason includes
    exception type), then exception propagates to asyncio.gather
    (return_exceptions=True) which surfaces it as a `_shard_exception_row`.
    """
    async with sem:
        discoveries = _read_discoveries(afs)
        agent_id = afs.spawn(meta["name"], config={"max_turns": MAX_TURNS})
        n_errors = meta["errors"].count("\n") + (1 if meta["errors"] else 0)
        line_budget = min(MAX_TOTAL_LINES, max(1, n_errors) * MAX_LINES_PER_ERROR)
        intent_id = log.intent(
            agent_id=agent_id,
            action=f"fix mypy in {meta['file_rel']}",
            metadata={"shard_idx": meta["idx"], "errors_before": n_errors},
        )

        closed = False
        try:
            target_abs = meta["wt"] / meta["file_rel"]
            prompt = _build_prompt(target_abs, meta["errors"], discoveries)

            timed_out = False
            try:
                body = await asyncio.wait_for(
                    ccr.run_agent(agent_id, prompt), timeout=SHARD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                body = ""
                timed_out = True
                logger.warning(
                    "shard %d (%s) timed out after %ds",
                    meta["idx"],
                    meta["name"],
                    SHARD_TIMEOUT_S,
                )

            pattern = _extract_pattern(body)
            clean = False if timed_out else _mypy_clean(meta["wt"], meta["file_rel"])
            patch = _capture_patch(meta["wt"], meta["idx"])
            diff_lines = _diff_line_count(patch)

            if pattern:
                try:
                    log.result(
                        agent_id=agent_id,
                        ref_id=intent_id,
                        payload={
                            "file": str(meta["file_rel"]),
                            "pattern": pattern,
                            "mypy_clean": clean,
                            "patch_bytes": patch.stat().st_size,
                        },
                    )
                except sqlite3.Error as exc:
                    logger.warning("shard %d log.result failed: %s", meta["idx"], exc)

            kept, reason = _classify_outcome(
                timed_out, clean, patch.stat().st_size, diff_lines, line_budget
            )

            try:
                if kept:
                    log.commit(
                        agent_id=agent_id,
                        intent_id=intent_id,
                        summary=f"kept patch for {meta['file_rel']}",
                    )
                else:
                    log.abort(agent_id=agent_id, ref_id=intent_id, reason=reason)
                closed = True
            except sqlite3.Error as exc:
                logger.warning("shard %d log close failed: %s", meta["idx"], exc)
                # closed stays False; finally will retry log.abort below.

            return _shard_outcome(
                idx=meta["idx"],
                file_rel=meta["file_rel"],
                name=meta["name"],
                agent_id=agent_id,
                body=body,
                pattern=pattern,
                clean=clean,
                patch=patch,
                diff_lines=diff_lines,
                n_errors=n_errors,
                line_budget=line_budget,
                kept=kept,
                reason=reason,
            )
        finally:
            # LogAct closure invariant — finally runs even if an exception
            # propagated past the inner asyncio.TimeoutError catch (e.g.,
            # httpx connect error, CancelledError, KeyError in CCR config).
            # Without this, the hub waits HUB_TEARDOWN_S for missing closes.
            if not closed:
                try:
                    log.abort(
                        agent_id=agent_id,
                        ref_id=intent_id,
                        reason="shard exited without commit/abort",
                    )
                except sqlite3.Error as exc:
                    logger.warning(
                        "shard %d fallback log.abort failed: %s",
                        meta["idx"],
                        exc,
                    )


# ── Driver (cancellation-safe hub + afs teardown) ───────────────────────


async def _teardown_hub(
    hub_task: asyncio.Task[dict[str, Any]],
    stop_event: asyncio.Event,
) -> dict[str, Any]:
    """Resolve the hub task. Three exit paths:

    1. Hub finished cleanly within HUB_TEARDOWN_S → return its summary.
    2. Hub did not finish in time → cancel, await cancellation, return
       a stub summary noting the timeout.
    3. OUR caller was cancelled (CancelledError) → cancel hub, await its
       cancellation, then re-raise so the cancellation propagates.
       Without this, the orphaned hub coroutine would resume after
       afs.close() in the outer finally and crash on closed SQLite.
    """
    stop_event.set()
    try:
        return await asyncio.wait_for(hub_task, timeout=HUB_TEARDOWN_S)
    except asyncio.TimeoutError:
        hub_task.cancel()
        try:
            await hub_task
        except (asyncio.CancelledError, sqlite3.Error):
            pass
        return {
            "patterns": [],
            "closed": 0,
            "summary": f"hub teardown timeout after {HUB_TEARDOWN_S}s",
        }
    except asyncio.CancelledError:
        hub_task.cancel()
        try:
            await hub_task
        except (asyncio.CancelledError, sqlite3.Error):
            pass
        raise


def _build_task_metas(files: list[Path], worktrees: dict[int, Path]) -> list[dict]:
    return [
        {
            "idx": idx,
            "file_rel": f,
            "wt": worktrees[idx],
            "errors": _errors_for(f),
            "name": f"mypyfix-{f.as_posix().replace('/', '_')}",
        }
        for idx, f in enumerate(files)
    ]


async def _drive_swarm(files: list[Path], db_path: str) -> tuple[list[dict], dict]:
    """Run all shards in parallel + the hub coroutine concurrently.

    Resource invariants:
      * afs.close() guaranteed via outer try/finally.
      * Hub task cancelled before afs.close() on every exit path,
        including outer cancellation (no orphaned SQLite touch).
    """
    from bene import Bene
    from bene.ccr import ClaudeCodeRunner
    from bene.router import TierRouter
    from bene.shared_log import SharedLog

    cfg = os.environ.get("BENE_CONFIG", "bene.yaml")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not cfg.startswith(".github/bene/"):
        raise RuntimeError(f"BENE_CONFIG must live under .github/bene/ in CI; got {cfg!r}")

    afs = Bene(db_path)
    hub_summary: dict[str, Any] = {"patterns": [], "closed": 0, "summary": "not started"}
    try:
        log = SharedLog(afs.conn)
        router = TierRouter.from_config(cfg)
        ccr = ClaudeCodeRunner(afs, router)

        worktrees = {idx: _make_worktree(idx) for idx in range(len(files))}
        task_metas = _build_task_metas(files, worktrees)

        sem = asyncio.Semaphore(ccr.max_parallel_agents)
        stop_event = asyncio.Event()
        hub_id = afs.spawn(HUB_NAME, config={"role": "blackboard"})
        hub_intent_id = log.intent(
            agent_id=hub_id,
            action="monitor and broadcast cross-shard patterns",
            metadata={"expected_shards": len(task_metas)},
        )
        hub_task = asyncio.create_task(
            _hub_task(afs, log, hub_id, hub_intent_id, stop_event, len(task_metas))
        )

        try:
            results = await asyncio.gather(
                *[_run_shard_lazy(afs, log, ccr, sem, meta) for meta in task_metas],
                return_exceptions=True,
            )
        finally:
            hub_summary = await _teardown_hub(hub_task, stop_event)

        summary: list[dict] = []
        for idx, res in enumerate(results):
            if isinstance(res, BaseException):
                summary.append(_shard_exception_row(idx, task_metas[idx], res))
            else:
                summary.append(res)
        return summary, hub_summary
    finally:
        afs.close()


# ── Render + IO ─────────────────────────────────────────────────────────


def _render_summary(sha: str, summary: list[dict], hub_summary: dict[str, Any]) -> str:
    n_kept = sum(1 for r in summary if r.get("kept"))
    n_discarded = len(summary) - n_kept
    n_timeouts = sum(1 for r in summary if "timeout" in str(r.get("reason", "")))
    lines = [
        "# BENE Refactor Swarm (mypy)",
        f"_sha: {sha}_  kept: {n_kept}  discarded: {n_discarded}  "
        f"timeouts: {n_timeouts}  "
        f"hub_patterns: {len(hub_summary.get('patterns', []))}",
        "",
        "| # | file | errs | mypy | diff/budget | kept | reason | patch |",
        "| - | ---- | ---- | ---- | ----------- | ---- | ------ | ----- |",
    ]
    for row in summary:
        lines.append(
            f"| {row['shard']} | `{row['file']}` | {row['errors_before']} | "
            f"{'OK' if row['mypy_clean'] else 'FAIL'} | "
            f"{row.get('diff_lines', 0)}/{row.get('line_budget', 0)} | "
            f"{'YES' if row.get('kept') else 'no'} | "
            f"{row.get('reason', '')} | "
            f"`{row['patch']}` ({row['patch_bytes']}B) |"
        )
    patterns = hub_summary.get("patterns") or []
    if patterns:
        lines += [
            "",
            "## Hub broadcast (live)",
            "",
            f"_{hub_summary.get('summary', '')}._",
            "",
        ]
        for i, p in enumerate(patterns, 1):
            lines.append(
                f"{i}. **{p.get('pattern')}**  \n"
                f"   _from shard `{p.get('shard')}` on `{p.get('file', '?')}`_"
            )
    lines += ["", "## Per-shard agent output", ""]
    for row in summary:
        lines += [
            f"### shard {row['shard']}: {row['file']}",
            "",
            row["body"] or "(empty)",
            "",
        ]
    return "\n".join(lines)


def _post_pr_comment(out_path: Path) -> None:
    pr = os.environ.get("PR_NUMBER")
    if not pr or not os.environ.get("GITHUB_TOKEN") or not shutil.which("gh"):
        return
    try:
        subprocess.run(
            ["gh", "pr", "comment", pr, "--body-file", str(out_path)],
            check=False,
            timeout=GH_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        # OSError covers TOCTOU between shutil.which() above and the actual
        # exec (binary removed, permission denied, etc.). Never fail PR
        # teardown over a missing CLI.
        logger.warning("gh pr comment failed: %s", exc)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


# ── Entrypoint (graceful degrade contract) ──────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-shards", type=int, default=8)
    ap.add_argument("--apply", action="store_true", help="Apply patches to HEAD")
    args = ap.parse_args()

    sha = _sha()
    out_md = OUT_DIR / f"swarm-{sha}.md"
    db_path = os.environ.get("BENE_DB", str(OUT_DIR / "refactor.db"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        files = _build_manifest(args.max_shards)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _write(out_md, f"# BENE Refactor Swarm\nManifest build failed: {e}\n")
        _post_pr_comment(out_md)
        return 0

    if not files:
        _write(out_md, "# BENE Refactor Swarm\nNo mypy errors. Nothing to do.\n")
        _post_pr_comment(out_md)
        return 0

    summary: list[dict] = []
    hub_summary: dict[str, Any] = {"patterns": [], "closed": 0, "summary": "n/a"}
    try:
        summary, hub_summary = asyncio.run(_drive_swarm(files, db_path))
    except ImportError as e:
        _write(out_md, f"# BENE Refactor Swarm\nbene not importable ({e}); skipped.\n")
        _post_pr_comment(out_md)
        return 0
    except RuntimeError as e:
        _write(out_md, f"# BENE Refactor Swarm\nSwarm aborted: {e}\n")
        _post_pr_comment(out_md)
        return 0
    except (OSError, subprocess.CalledProcessError) as e:
        # git binary missing OR git command exits non-zero during worktree
        # setup. Graceful-degrade contract: produce a markdown report and
        # exit 0 so CI surfaces the issue without a hard crash.
        _write(out_md, f"# BENE Refactor Swarm\nSwarm aborted: {type(e).__name__}: {e}\n")
        _post_pr_comment(out_md)
        return 0
    finally:
        try:
            _cleanup_worktrees()
        except OSError as exc:
            # Cleanup is best-effort — missing git binary at teardown must
            # not mask the swarm's exit state. Log and move on.
            logger.warning("_cleanup_worktrees skipped: %s", exc)

    _write(out_md, _render_summary(sha, summary, hub_summary))
    _write(OUT_DIR / f"swarm-{sha}.json", json.dumps(summary, indent=2))

    if args.apply:
        applied = _apply_and_push(summary)
        if applied:
            print(f"applied + pushed {applied} kept patch(es)")
        else:
            print("no kept patches to apply")

    _post_pr_comment(out_md)
    print(f"wrote {out_md}")
    return 0


def _apply_and_push(summary: list[dict]) -> int:
    """Apply kept patches, commit, and push to the PR head ref.

    Returns the count of patches applied. No-op (returns 0) if nothing kept
    or if pushing isn't configured (missing env). Failures are logged but
    don't abort — the swarm comment + artifacts still go up.

    Invariants enforced (matches the rest of the module):
      - Every subprocess.run carries timeout=.
      - Narrow `(subprocess.TimeoutExpired, OSError)` catches; nothing else.
      - `--` separator on `git apply` to neutralize patch paths beginning
        with `-`.
    """
    kept = [row for row in summary if row.get("kept")]
    if not kept:
        return 0

    pr_head = os.environ.get("GITHUB_HEAD_REF")
    if not pr_head:
        print("skip auto-apply: GITHUB_HEAD_REF not set (not a PR run)")
        return 0

    applied = 0
    for row in kept:
        patch = REPO_ROOT / row["patch"]
        try:
            result = subprocess.run(
                ["git", "apply", "--", str(patch)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("git apply failed for %s: %s", patch, exc)
            continue
        if result.returncode != 0:
            print(f"skip patch {row['patch']}: {result.stderr.strip()}")
            continue
        applied += 1

    if applied == 0:
        return 0

    def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                check=False,
                capture_output=capture,
                text=True,
                timeout=GIT_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("git %s failed: %s", " ".join(cmd[1:3]), exc)
            return None

    _run(["git", "config", "user.name", "bene-refactor-swarm[bot]"])
    _run(["git", "config", "user.email", "bene-refactor-swarm@users.noreply.github.com"])
    _run(["git", "add", "-A"])

    msg = (
        f"chore(typecheck): refactor-swarm auto-apply ({applied} kept patch(es))\n\n"
        "WHAT: apply mypy-clean patches produced by the BENE Refactor Swarm.\n"
        "WHY:  PR carries the 'auto-apply-swarm' label.\n"
        "HOW:  scripts/ci/refactor_swarm.py --apply.\n\n"
        "CR: bene-team\n"
    )
    commit = _run(["git", "commit", "-m", msg], capture=True)
    if commit is None or commit.returncode != 0:
        stderr = (commit.stderr.strip() or commit.stdout.strip()) if commit else "subprocess error"
        print(f"skip auto-apply commit: {stderr}")
        return 0

    push = _run(["git", "push", "origin", f"HEAD:{pr_head}"], capture=True)
    if push is None or push.returncode != 0:
        stderr = push.stderr.strip() if push else "subprocess error"
        print(f"auto-apply push failed: {stderr}")
        return 0

    return applied


if __name__ == "__main__":
    sys.exit(main())
