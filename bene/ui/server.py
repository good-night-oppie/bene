"""BENE Web UI Server — Starlette backend for the agent observability dashboard.

Reads any bene.db file directly via sqlite3 (read-only).
Multi-project: every endpoint accepts ?db=<path> query param.
Projects list persisted in ~/.bene/ui_projects.json.

Launch via: bene ui [--db PATH] [--port 8765]
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import sqlite3
import time
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, AsyncGenerator

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from bene._safe import safe_json_loads


class _SuppressConnReset(logging.Filter):
    """Filter out Windows [WinError 10054] ConnectionResetError noise from uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "WinError 10054" not in msg and "ConnectionResetError" not in msg


_conn_reset_filter = _SuppressConnReset()

PROJECTS_FILE = Path.home() / ".bene" / "ui_projects.json"
STATIC_DIR = Path(__file__).parent / "static"

# ── Helpers ────────────────────────────────────────────────────────────────


def _is_bene_db(path: str) -> bool:
    """Return True if file is a valid BENE database (has agents table)."""
    try:
        with closing(sqlite3.connect(path)) as conn:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        return "agents" in tables
    except sqlite3.Error:
        return False


def _scan_dbs(directory: str) -> list[dict]:
    """Scan directory for valid BENE .db files, sorted by agent count desc."""
    results = []
    for db_file in sorted(glob.glob(os.path.join(directory, "*.db"))):
        if not _is_bene_db(db_file):
            continue
        try:
            with closing(sqlite3.connect(db_file)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        except sqlite3.Error:
            continue
        results.append(
            {
                "path": db_file,
                "name": Path(db_file).stem,
                "agent_count": count,
            }
        )
    return sorted(results, key=lambda x: -x["agent_count"])


def _resolve_db(raw: str) -> str:
    """Resolve a path that may be a directory to a valid BENE DB file."""
    p = Path(raw)
    if p.is_file():
        return str(p)
    if p.is_dir():
        # Prefer bene.db if valid, otherwise pick the DB with most agents
        default = p / "bene.db"
        if default.exists() and _is_bene_db(str(default)):
            return str(default)
        dbs = _scan_dbs(str(p))
        if dbs:
            return dbs[0]["path"]
        raise ValueError(
            f"No valid BENE database found in '{raw}'. Expected a .db file with an 'agents' table."
        )
    return raw  # let downstream give a normal "file not found" error


def _db_path(request: Request) -> str:
    raw = request.query_params.get("db", "./bene.db")
    return _resolve_db(raw)


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, uri=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _rows(db_path: str, sql: str, params=()) -> list[dict]:
    try:
        with closing(_conn(db_path)) as conn:
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        raise RuntimeError(f"DB error ({db_path}): {e}") from e


def _one(db_path: str, sql: str, params=()) -> dict | None:
    rows = _rows(db_path, sql, params)
    return rows[0] if rows else None


def _json(data, status=200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def _err(msg: str, status=400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


def _load_projects() -> list[dict]:
    if PROJECTS_FILE.exists():
        return safe_json_loads(PROJECTS_FILE.read_text(), default=[]) or []
    return []


def _save_projects(projects: list[dict]) -> None:
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))


_JSON_FIELD_MISSING: Any = object()


def _parse_json_fields(rows: list[dict], fields: tuple[str, ...], on_error: str = "keep") -> None:
    """Parse JSON-encoded fields on each row in-place.

    Narrows the catch to the three exceptions ``json.loads`` raises:
    ``JSONDecodeError`` (bad syntax), ``TypeError`` (non-str/bytes),
    ``ValueError`` (numeric edge cases). Other exceptions propagate so real
    defects (e.g. ``KeyError`` on a mistyped field name) are not masked.

    on_error:
        "keep"   leave the raw string value untouched (e.g. event payloads).
        "empty"  replace with ``{}`` (e.g. config/metadata blobs).
    """
    for row in rows:
        for field in fields:
            value = row.get(field)
            if not value:
                continue
            try:
                row[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError, ValueError):
                if on_error == "empty":
                    row[field] = {}
                # else: keep raw string


# ── API Handlers ───────────────────────────────────────────────────────────


async def api_stats(request: Request) -> JSONResponse:
    """GET /api/stats?db=PATH — aggregate dashboard stats."""
    db = _db_path(request)
    try:
        totals = (
            _one(
                db,
                """
            SELECT
                COUNT(*) as total_agents,
                COALESCE(SUM(CASE WHEN status='running' THEN 1 ELSE 0 END), 0) as running,
                COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0) as completed,
                COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), 0) as failed,
                COALESCE(SUM(CASE WHEN status='paused' THEN 1 ELSE 0 END), 0) as paused,
                COALESCE(SUM(CASE WHEN status='killed' THEN 1 ELSE 0 END), 0) as killed,
                COALESCE(SUM(CASE WHEN status='initialized' THEN 1 ELSE 0 END), 0) as initialized
            FROM agents
        """,
            )
            or {}
        )

        event_count = _one(db, "SELECT COUNT(*) as n FROM events") or {}
        tool_count = _one(db, "SELECT COUNT(*) as n FROM tool_calls") or {}
        token_sum = _one(db, "SELECT COALESCE(SUM(token_count),0) as n FROM tool_calls") or {}

        return _json(
            {
                "agents": totals,
                "events": event_count.get("n", 0),
                "tool_calls": tool_count.get("n", 0),
                "tokens": token_sum.get("n", 0),
            }
        )
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_agents(request: Request) -> JSONResponse:
    """GET /api/agents?db=PATH — all agents with stats for graph."""
    db = _db_path(request)
    try:
        rows = _rows(
            db,
            """
            SELECT
                a.agent_id,
                a.name,
                a.parent_id,
                a.status,
                a.config,
                a.metadata,
                a.created_at,
                a.last_heartbeat,
                (SELECT COUNT(*) FROM files WHERE agent_id = a.agent_id AND deleted=0) AS file_count,
                (SELECT COUNT(*) FROM tool_calls WHERE agent_id = a.agent_id) AS tool_call_count,
                (SELECT COALESCE(SUM(token_count), 0) FROM tool_calls WHERE agent_id = a.agent_id) AS token_count,
                (SELECT COUNT(*) FROM events WHERE agent_id = a.agent_id) AS event_count,
                strftime('%Y-%m-%dT%H:%M', a.created_at) AS batch_minute,
                COALESCE((SELECT value FROM state WHERE agent_id = a.agent_id AND key = 'task'), '') AS task_description
            FROM agents a
            ORDER BY a.created_at DESC
        """,
        )
        _parse_json_fields(rows, ("config", "metadata"), on_error="empty")

        # Compute batch_id: group agents by same-minute creation into batches of size >= 2
        minute_counts = Counter(r["batch_minute"] for r in rows if r.get("batch_minute"))
        batch_minutes = {m for m, n in minute_counts.items() if n >= 2}
        for r in rows:
            m = r.get("batch_minute")
            r["batch_id"] = m if m in batch_minutes else None

        return _json(rows)
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_agent_detail(request: Request) -> JSONResponse:
    """GET /api/agents/{id}?db=PATH — single agent detail."""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        row = _one(
            db,
            """
            SELECT
                a.agent_id, a.name, a.parent_id, a.status,
                a.config, a.metadata, a.created_at, a.last_heartbeat, a.pid,
                (SELECT COUNT(*) FROM files WHERE agent_id = a.agent_id AND deleted=0) AS file_count,
                (SELECT COUNT(*) FROM tool_calls WHERE agent_id = a.agent_id) AS tool_call_count,
                (SELECT COALESCE(SUM(token_count), 0) FROM tool_calls WHERE agent_id = a.agent_id) AS token_count,
                (SELECT COUNT(*) FROM events WHERE agent_id = a.agent_id) AS event_count,
                (SELECT value FROM state WHERE agent_id = a.agent_id AND key = 'task') AS task_description
            FROM agents a
            WHERE a.agent_id = ?
        """,
            (agent_id,),
        )
        if not row:
            return _err("Agent not found", 404)
        _parse_json_fields([row], ("config", "metadata"), on_error="empty")
        return _json(row)
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_agent_events(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/events?db=PATH&limit=100&since=EVENT_ID"""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    limit = int(request.query_params.get("limit", 200))
    since = request.query_params.get("since")
    try:
        if since:
            rows = _rows(
                db,
                """
                SELECT event_id, agent_id, event_type, payload, timestamp
                FROM events WHERE agent_id=? AND event_id > ?
                ORDER BY event_id ASC LIMIT ?
            """,
                (agent_id, int(since), limit),
            )
        else:
            rows = _rows(
                db,
                """
                SELECT event_id, agent_id, event_type, payload, timestamp
                FROM events WHERE agent_id=?
                ORDER BY event_id DESC LIMIT ?
            """,
                (agent_id, limit),
            )
            rows.reverse()
        _parse_json_fields(rows, ("payload",), on_error="keep")
        return _json(rows)
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_agent_tool_calls(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/tool_calls?db=PATH — nested tool call tree."""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        rows = _rows(
            db,
            """
            SELECT call_id, agent_id, tool_name, input, output, status,
                   started_at, completed_at, duration_ms, token_count,
                   parent_call_id, error_message
            FROM tool_calls WHERE agent_id=?
            ORDER BY started_at ASC
        """,
            (agent_id,),
        )
        _parse_json_fields(rows, ("input", "output"), on_error="keep")
        # Build nested tree
        by_id = {r["call_id"]: {**r, "children": []} for r in rows}
        roots = []
        for r in by_id.values():
            pid = r.get("parent_call_id")
            if pid and pid in by_id:
                by_id[pid]["children"].append(r)
            else:
                roots.append(r)
        return _json(roots)
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_agent_checkpoints(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/checkpoints?db=PATH"""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        rows = _rows(
            db,
            """
            SELECT checkpoint_id, agent_id, label, created_at, event_id, metadata
            FROM checkpoints WHERE agent_id=?
            ORDER BY created_at ASC
        """,
            (agent_id,),
        )
        _parse_json_fields(rows, ("metadata",), on_error="empty")
        return _json(rows)
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_agent_files(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/files?db=PATH&path=/"""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    path = request.query_params.get("path", "/")
    # Normalize path
    if not path.startswith("/"):
        path = "/" + path
    try:
        # List direct children of path
        if path == "/":
            rows = _rows(
                db,
                """
                SELECT file_id, path, is_dir, size, modified_at, version, content_hash
                FROM files
                WHERE agent_id=? AND deleted=0
                  AND (
                    path = '/' OR
                    (path LIKE '/_%' AND INSTR(SUBSTR(path, 2), '/') = 0)
                  )
                ORDER BY is_dir DESC, path ASC
            """,
                (agent_id,),
            )
        else:
            # Children under path/
            prefix = path.rstrip("/") + "/"
            plen = len(prefix)
            rows = _rows(
                db,
                """
                SELECT file_id, path, is_dir, size, modified_at, version, content_hash
                FROM files
                WHERE agent_id=? AND deleted=0
                  AND path LIKE ? ESCAPE '\\'
                ORDER BY is_dir DESC, path ASC
            """,
                (agent_id, prefix.replace("%", "\\%").replace("_", "\\_") + "%"),
            )

            # Filter to direct children only (no deeper nesting)
            def is_direct(p):
                rel = p[plen:]
                return rel and "/" not in rel

            rows = [r for r in rows if is_direct(r["path"])]

        return _json(
            {
                "path": path,
                "entries": rows,
            }
        )
    except RuntimeError as e:
        return _err(str(e), 500)


async def api_projects_get(request: Request) -> JSONResponse:
    """GET /api/projects — list known projects."""
    projects = _load_projects()
    # Enrich with existence check
    for p in projects:
        p["exists"] = Path(p["path"]).exists()
    return _json(projects)


async def api_projects_post(request: Request) -> JSONResponse:
    """POST /api/projects — add a project. Body: {path: str, name?: str}

    If path is a directory, scans it for all valid BENE .db files and adds them all.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _err("Invalid JSON body")
    raw_path = body.get("path", "").strip()
    if not raw_path:
        return _err("path is required")

    p = Path(raw_path).resolve()
    projects = _load_projects()
    added: list[str] = []

    if p.is_dir():
        dbs = _scan_dbs(str(p))
        if not dbs:
            return _err(
                f"No valid BENE databases found in '{p}'. "
                "Expected one or more .db files with an 'agents' table."
            )
        for db in dbs:
            db_abs = str(Path(db["path"]).resolve())
            if not any(proj["path"] == db_abs for proj in projects):
                projects.insert(
                    0,
                    {
                        "path": db_abs,
                        "name": db["name"],
                        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                )
                added.append(db_abs)
    else:
        db_abs = str(p)
        if not any(proj["path"] == db_abs for proj in projects):
            name = body.get("name") or p.stem or p.parent.name or db_abs
            projects.insert(
                0,
                {
                    "path": db_abs,
                    "name": name,
                    "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
            added.append(db_abs)

    if added:
        _save_projects(projects)

    # Return the first added path so the frontend can switch to it
    first = added[0] if added else (projects[0]["path"] if projects else None)
    return _json({"ok": True, "projects": projects, "added": added, "switch_to": first})


# ── Graph API ─────────────────────────────────────────────────────────────


def _wave_title(names: list[str]) -> str:
    """Derive a human-readable wave title from agent names."""
    if not names:
        return "Wave"
    counts: dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1

    # Pure meta-harness orchestrator
    if all(n == "meta-harness-search" for n in names):
        return "Meta-Harness"

    # Proposer iterations
    proposers = [n for n in names if n.startswith("proposer-iter")]
    if proposers:
        iters = sorted({n.rsplit("-", 1)[-1] for n in proposers})
        return f"Proposer · iter {', '.join(iters)}"

    # Harness (evaluation) waves
    harnesses = [n for n in names if n.startswith("harness-")]
    if len(harnesses) == len(names):
        return f"Eval · {len(names)} harnesses"
    if harnesses:
        non_h = [n for n in names if not n.startswith("harness-")]
        return f"Mixed: {non_h[0] if non_h else ''} + {len(harnesses)} harnesses"

    # Research-role waves
    research = {
        "base-architect",
        "slot-optimizer",
        "quant-master",
        "training-optimizer",
        "innovation-researcher",
        "compression-expert",
        "ensemble-master",
        "researcher",
    }
    found = [n for n in names if n in research]
    if found:
        return "Research Wave"

    # Dominant single name
    dominant = max(counts, key=lambda k: counts[k])
    if counts[dominant] > len(names) // 2:
        label = dominant.replace("-", " ").title()
        extra = len(names) - counts[dominant]
        return label + (f" +{extra}" if extra else "")

    # Generic: list first 2 unique names
    unique = list(dict.fromkeys(names))[:2]
    label = " · ".join(n.replace("-", " ") for n in unique)
    if len(names) > 2:
        label += f" +{len(names) - 2}"
    return label


def _parse_score(scores_json: str) -> float | None:
    """Extract best accuracy from scores JSON (list or dict shape)."""
    sc = safe_json_loads(scores_json, default=None)
    if isinstance(sc, list):
        vals = [acc for s in sc if isinstance(s, dict) and (acc := s.get("accuracy")) is not None]
        return max(vals) if vals else None
    if isinstance(sc, dict):
        accuracy = sc.get("accuracy")
        if isinstance(accuracy, (int, float)):
            return float(accuracy)
    return None


def _parse_tokens(usage_json: str) -> int:
    """Extract total_tokens from usage JSON, falling back to 0."""
    u = safe_json_loads(usage_json, default=None)
    if not isinstance(u, dict):
        return 0
    raw = u.get("total_tokens")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def api_engrams(request: Request) -> JSONResponse:
    """GET /api/engrams?db=PATH&kind=&agent=&limit= — engram browser (BENE 2.0)."""
    db = _db_path(request)
    kind = request.query_params.get("kind")
    agent = request.query_params.get("agent")
    limit = min(int(request.query_params.get("limit", "50")), 200)
    try:
        sql = (
            "SELECT engram_id, kind, tier, title, agent_id, created_at, superseded_by"
            " FROM engrams WHERE 1=1"
        )
        params: list = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if agent:
            sql += " AND agent_id = ?"
            params.append(agent)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = _rows(db, sql, tuple(params))
        counts = _rows(db, "SELECT kind, COUNT(*) as n FROM engrams GROUP BY kind ORDER BY n DESC")
        return _json({"engrams": rows, "counts": counts})
    except Exception as e:
        if "no such table" in str(e):
            return _json(
                {"engrams": [], "counts": [], "note": "kernel v2 tables not present in this db"}
            )
        return _err(str(e), 500)


async def api_trust(request: Request) -> JSONResponse:
    """GET /api/trust/{id}?db=PATH — computed per-agent trust summary (BENE 2.0)."""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        import sqlite3 as _sq

        from bene.kernel.trust import TrustLedger

        conn = _sq.connect(f"file:{db}?mode=ro", uri=True)
        try:
            summary = TrustLedger(conn).summary(agent_id)
        finally:
            conn.close()
        return _json(summary)
    except Exception as e:
        if "no such table" in str(e):
            return _json({"agent_id": agent_id, "note": "kernel v2 tables not present in this db"})
        return _err(str(e), 500)


async def api_graph(request: Request) -> JSONResponse:
    """GET /api/graph?db=PATH — nodes + edges for the execution graph."""
    db = _db_path(request)
    try:
        agents = _rows(
            db,
            """
            SELECT
                a.agent_id, a.name, a.parent_id, a.status,
                strftime('%Y-%m-%dT%H:%M', a.created_at) AS batch_minute,
                COALESCE((SELECT value FROM state WHERE agent_id = a.agent_id AND key = 'task'), '') AS task,
                COALESCE((SELECT value FROM state WHERE agent_id = a.agent_id AND key = 'scores'), '') AS scores_json,
                COALESCE((SELECT value FROM state WHERE agent_id = a.agent_id AND key = 'usage'), '') AS usage_json,
                (SELECT COUNT(*) FROM events WHERE agent_id = a.agent_id AND event_type = 'file_write') AS file_count,
                (SELECT COUNT(*) FROM events WHERE agent_id = a.agent_id AND event_type = 'tool_call_start') AS tool_count
            FROM agents a
            ORDER BY a.created_at ASC
        """,
        )

        # ── Group into waves (batch_minute groups ≥ 2 agents) ────────────
        minute_agents: dict[str, list] = defaultdict(list)
        for a in agents:
            if a.get("batch_minute"):
                minute_agents[a["batch_minute"]].append(a)
        batch_minutes = {m for m, grp in minute_agents.items() if len(grp) >= 2}

        nodes: list[dict] = []
        edges: list[dict] = []
        agent_ids = {a["agent_id"] for a in agents}

        # ── Wave nodes ────────────────────────────────────────────────────
        sorted_minutes = sorted(batch_minutes)
        wave_node_ids: list[str] = []
        for minute in sorted_minutes:
            wave_agents = minute_agents[minute]
            names = [a["name"] for a in wave_agents]
            title = _wave_title(names)

            # Best score + completion stats
            scores = [
                s for s in (_parse_score(a["scores_json"]) for a in wave_agents) if s is not None
            ]
            best_score = max(scores) if scores else None
            n_done = sum(1 for a in wave_agents if a["status"] == "completed")
            n_fail = sum(1 for a in wave_agents if a["status"] == "failed")

            wave_id = f"wave:{minute}"
            wave_node_ids.append(wave_id)
            nodes.append(
                {
                    "id": wave_id,
                    "type": "wave",
                    "label": title,
                    "timestamp": minute,
                    "agent_count": len(wave_agents),
                    "completed": n_done,
                    "failed": n_fail,
                    "best_score": round(best_score, 3) if best_score is not None else None,
                }
            )

        # ── Agent nodes ───────────────────────────────────────────────────
        for a in agents:
            score = _parse_score(a["scores_json"])
            tokens = _parse_tokens(a["usage_json"])
            raw_task = a.get("task") or ""
            parsed_task = safe_json_loads(raw_task, default=raw_task)
            task_str = str(parsed_task).replace("\n", " ").strip()

            nodes.append(
                {
                    "id": a["agent_id"],
                    "type": "agent",
                    "label": a["name"],
                    "status": a["status"],
                    "task": task_str[:300],
                    "score": round(score, 3) if score is not None else None,
                    "file_count": int(a["file_count"]),
                    "tool_count": int(a["tool_count"]),
                    "token_count": tokens,
                    "batch_minute": a.get("batch_minute"),
                }
            )

        # ── Edges: parent→child spawn ─────────────────────────────────────
        for a in agents:
            pid = a.get("parent_id")
            if pid and pid in agent_ids:
                edges.append(
                    {
                        "id": f"spawn:{pid}:{a['agent_id']}",
                        "source": pid,
                        "target": a["agent_id"],
                        "type": "spawn",
                    }
                )

        # ── Edges: wave → member agents ───────────────────────────────────
        for a in agents:
            bm = a.get("batch_minute")
            if bm and bm in batch_minutes:
                edges.append(
                    {
                        "id": f"wm:{bm}:{a['agent_id']}",
                        "source": f"wave:{bm}",
                        "target": a["agent_id"],
                        "type": "wave_member",
                    }
                )

        # ── Edges: wave → next wave (temporal flow) ───────────────────────
        for i in range(len(wave_node_ids) - 1):
            edges.append(
                {
                    "id": f"wseq:{i}",
                    "source": wave_node_ids[i],
                    "target": wave_node_ids[i + 1],
                    "type": "wave_sequence",
                }
            )

        return _json({"nodes": nodes, "edges": edges})
    except RuntimeError as e:
        return _err(str(e), 500)


# ── SSE Stream ────────────────────────────────────────────────────────────


async def _event_generator(db: str) -> AsyncGenerator[bytes, None]:
    """Poll DB every 2s, emit new events and agent status changes.

    The outer try/except in the loop is narrowed to ``sqlite3.Error`` and
    ``RuntimeError`` (raised by ``_rows`` on DB error); anything else
    (typically programmer error in payload shaping) propagates so the SSE
    stream fails fast instead of silently looping.
    """
    last_event_id = 0
    last_agent_snapshot: dict[str, str] = {}

    # Get current max event_id; a missing events table just means start at 0.
    try:
        row = _one(db, "SELECT COALESCE(MAX(event_id),0) as m FROM events")
        last_event_id = row["m"] if row else 0
    except (sqlite3.Error, RuntimeError):
        last_event_id = 0

    while True:
        try:
            # New events
            new_events = _rows(
                db,
                """
                SELECT event_id, agent_id, event_type, payload, timestamp
                FROM events WHERE event_id > ?
                ORDER BY event_id ASC LIMIT 50
            """,
                (last_event_id,),
            )

            for ev in new_events:
                last_event_id = ev["event_id"]
                if ev.get("payload"):
                    ev["payload"] = safe_json_loads(ev["payload"], default=ev["payload"])
                data = json.dumps({"type": "new_event", "event": ev})
                yield f"data: {data}\n\n".encode()

            # Agent status changes
            agents = _rows(db, "SELECT agent_id, status, name, last_heartbeat FROM agents")
            for a in agents:
                aid = a["agent_id"]
                if last_agent_snapshot.get(aid) != a["status"]:
                    last_agent_snapshot[aid] = a["status"]
                    data = json.dumps({"type": "agent_update", "agent": a})
                    yield f"data: {data}\n\n".encode()

        except (sqlite3.Error, RuntimeError) as e:
            data = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {data}\n\n".encode()

        await asyncio.sleep(2)


async def api_events_stream(request: Request) -> StreamingResponse:
    """GET /api/events/stream?db=PATH — SSE stream."""
    db = _db_path(request)

    async def generator():
        try:
            yield b'data: {"type": "connected"}\n\n'
            async for chunk in _event_generator(db):
                if await request.is_disconnected():
                    break
                yield chunk
        except (ConnectionResetError, GeneratorExit, asyncio.CancelledError):
            pass  # client disconnected — normal on Windows (WinError 10054)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── App ────────────────────────────────────────────────────────────────────


def create_app() -> Starlette:
    routes = [
        Route("/api/stats", api_stats),
        Route("/api/agents", api_agents),
        Route("/api/agents/{id}", api_agent_detail),
        Route("/api/agents/{id}/events", api_agent_events),
        Route("/api/agents/{id}/tool_calls", api_agent_tool_calls),
        Route("/api/agents/{id}/checkpoints", api_agent_checkpoints),
        Route("/api/agents/{id}/files", api_agent_files),
        Route("/api/engrams", api_engrams),
        Route("/api/trust/{id}", api_trust),
        Route("/api/graph", api_graph),
        Route("/api/events/stream", api_events_stream),
        Route("/api/projects", api_projects_get, methods=["GET"]),
        Route("/api/projects", api_projects_post, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True)),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()


def run(host: str = "127.0.0.1", port: int = 8765, db: str = "./bene.db") -> None:
    """Launch the UI server. Called from CLI."""
    # Auto-register the project
    db_abs = str(Path(db).resolve())
    projects = _load_projects()
    if not any(p["path"] == db_abs for p in projects):
        name = Path(db_abs).parent.name or db_abs
        projects.insert(
            0,
            {
                "path": db_abs,
                "name": name,
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        _save_projects(projects)

    print(f"  BENE UI  →  http://{host}:{port}/?db={db_abs}")
    # Suppress Windows [WinError 10054] noise from client disconnects
    for _lgr in ("uvicorn", "uvicorn.error", "uvicorn.access", "asyncio"):
        logging.getLogger(_lgr).addFilter(_conn_reset_filter)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
