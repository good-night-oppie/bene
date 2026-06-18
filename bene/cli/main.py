"""BENE CLI — command-line interface for the Breeding-program Evolutionary Nexus for Engrams."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import cast

# Fix Windows cp1252 encoding crash — force UTF-8 for stdout/stderr
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from bene import __version__
from bene.config import load_config, runner_kwargs_from_config
from bene.core import Bene

console = Console()

DEFAULT_DB = os.environ.get("BENE_DB", "./bene.db")
DEFAULT_CONFIG = os.environ.get("BENE_CONFIG", "./bene.yaml")


def _get_afs(db: str) -> Bene:
    """Get or create a BENE instance."""
    return Bene(db_path=db)


def _json_out(ctx, data):
    """Output data as JSON if --json is set, otherwise return False."""
    if ctx.obj.get("json"):
        click.echo(json.dumps(data, indent=2, default=str))
        return True
    return False


def _json_err(ctx, msg: str):
    """Output error as JSON if --json is set, otherwise return False."""
    if ctx.obj.get("json"):
        click.echo(json.dumps({"error": msg}))
        ctx.exit(1)
        return True
    return False


@click.group()
@click.version_option(version=__version__, prog_name="bene")
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output structured JSON (auto-enabled when piped)",
)
@click.pass_context
def cli(ctx, json_output):
    """BENE — Breeding-program Evolutionary Nexus for Engrams.

    Every agent gets an isolated, auditable, portable virtual
    filesystem backed by SQLite. Embrace the BENE.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output or not sys.stdout.isatty()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def init(db: str):
    """Initialize a new BENE database."""
    if Path(db).exists():
        console.print(f"[yellow]Database already exists:[/yellow] {db}")
        return

    afs = _get_afs(db)
    afs.close()
    console.print(f"[green]Initialized BENE database:[/green] {db}")


@cli.command()
@click.option("-o", "--output", default="./bene.yaml", help="Output config file path")
def setup(output: str):
    """Interactive setup wizard — configure BENE for your project."""
    from bene.cli.setup import run_setup

    run_setup(output_path=output)


@cli.command()
@click.argument("task")
@click.option("--name", "-n", required=True, help="Agent name")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option("--model", "-m", help="Force a specific model")
@click.option("--checkpoint-interval", default=10, help="Auto-checkpoint every N iterations")
@click.option(
    "--ask/--no-ask",
    default=False,
    help="Run the intake step first: analyze the task and ask any clarifying "
    "questions the builder genuinely needs before starting (0 or more — dynamic, "
    "no fixed count).",
)
@click.option(
    "--answers",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a JSON file with pre-filled answers (for non-interactive --ask).",
)
@click.option(
    "--intake-only",
    is_flag=True,
    default=False,
    help="Run only the intake step and print the questions as JSON. Does not spawn "
    "an agent. Useful for scripting or previewing.",
)
def run(
    task: str,
    name: str,
    db: str,
    config_file: str,
    model: str,
    checkpoint_interval: int,
    ask: bool,
    answers: str,
    intake_only: bool,
):
    """Spawn and run an agent with a task."""
    from bene.ccr.runner import ClaudeCodeRunner
    from bene.router.tier import TierRouter

    afs = _get_afs(db)

    if not Path(config_file).exists():
        console.print(f"[red]Config file not found:[/red] {config_file}")
        console.print("Run: cp bene.yaml.example bene.yaml")
        return

    config = load_config(config_file)
    router = TierRouter.from_config(config_file)

    # ── Intake step (dynamic clarifying questions) ──────────────────
    if ask or intake_only:
        from bene.intake import analyze, ask_interactively, enrich_task

        try:
            questions = asyncio.run(analyze(task, router, force_model=model))
        except Exception as e:
            console.print(f"[red]Intake step failed:[/red] {e}")
            afs.close()
            return

        if intake_only:
            click.echo(json.dumps([q.to_dict() for q in questions], indent=2))
            afs.close()
            return

        if not questions:
            console.print(
                "[green]\u2714 intake-agent:[/green] task is fully specified. "
                "No questions — proceeding."
            )
        else:
            if answers:
                with open(answers) as f:
                    answer_map = json.load(f)
            else:
                answer_map = ask_interactively(questions)
            task = enrich_task(task, answer_map)

    ccr = ClaudeCodeRunner(
        afs,
        router,
        checkpoint_interval=checkpoint_interval,
        **runner_kwargs_from_config(config),
    )

    agent_config = {}
    if model:
        agent_config["force_model"] = model

    agent_id = afs.spawn(name=name, config=agent_config)
    console.print(f"[cyan]Spawned agent:[/cyan] {agent_id} ({name})")

    try:
        result = asyncio.run(ccr.run_agent(agent_id, task))
        console.print(f"\n[green]Result:[/green]\n{result}")
    except Exception as e:
        console.print(f"\n[red]Agent failed:[/red] {e}")
    finally:
        afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option(
    "--task",
    "-t",
    multiple=True,
    nargs=2,
    metavar="NAME PROMPT",
    help="Task as --task NAME PROMPT (can specify multiple)",
)
def parallel(db: str, config_file: str, task: tuple):
    """Run multiple agents in parallel."""
    from bene.ccr.runner import ClaudeCodeRunner
    from bene.router.tier import TierRouter

    if not task:
        console.print("[red]No tasks specified. Use --task NAME PROMPT[/red]")
        return

    afs = _get_afs(db)
    config = load_config(config_file)
    router = TierRouter.from_config(config_file)
    ccr = ClaudeCodeRunner(afs, router, **runner_kwargs_from_config(config))

    tasks = [{"name": t[0], "prompt": t[1]} for t in task]

    console.print(f"[cyan]Running {len(tasks)} agents in parallel...[/cyan]")
    results = asyncio.run(ccr.run_parallel(tasks))

    for i, result in enumerate(results):
        console.print(f"\n[bold]Agent {tasks[i]['name']}:[/bold]")
        console.print(result[:500])

    afs.close()


@cli.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--status", "-s", help="Filter by status")
@click.pass_context
def list_agents(ctx, db: str, status: str):
    """List all agents."""
    if not os.path.exists(db):
        if ctx.obj.get("json"):
            click.echo(
                json.dumps(
                    {
                        "agents": [],
                        "note": f"no database at {db}",
                        "next_steps": [
                            "bene init",
                            "bene demo --no-ui",
                            'bene run "task" --name agent',
                        ],
                    }
                )
            )
            return
        console.print(f"[yellow]No database at[/yellow] {db}")
        console.print("Get started:")
        console.print("  [cyan]bene init[/cyan]            create a database here")
        console.print(
            "  [cyan]bene demo --no-ui[/cyan]    see the 5-pillar story in <60s (keyless)"
        )
        console.print('  [cyan]bene run "task" --name my-agent[/cyan]   run your first agent')
        return
    afs = _get_afs(db)
    agents = afs.list_agents(status_filter=status)

    if _json_out(ctx, agents):
        afs.close()
        return

    if not agents:
        console.print("[dim]No agents found[/dim]")
        return

    table = Table(title="Agents")
    table.add_column("ID", style="cyan", max_width=14)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Created")

    for agent in agents:
        status_text = Text(agent["status"])
        if agent["status"] == "running":
            status_text.stylize("bold green")
        elif agent["status"] == "completed":
            status_text.stylize("green")
        elif agent["status"] in ("failed", "killed"):
            status_text.stylize("red")

        table.add_row(
            agent["agent_id"][:12] + "...",
            agent["name"],
            status_text,
            agent["created_at"][:19] if agent["created_at"] else "",
        )

    console.print(table)
    afs.close()


@cli.command()
@click.argument("sql")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def query(ctx, sql: str, db: str):
    """Run a read-only SQL query against the agent database."""
    afs = _get_afs(db)
    try:
        results = afs.query(sql)
        if _json_out(ctx, results):
            return
        if results:
            table = Table()
            for col in results[0].keys():
                table.add_column(col)
            for row in results:
                table.add_row(*[str(v)[:80] for v in row.values()])
            console.print(table)
        else:
            console.print("[dim]No results[/dim]")
    except PermissionError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    except Exception as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]Query error: {e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--label", "-l", help="Optional checkpoint label")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def checkpoint(ctx, agent_id: str, label: str, db: str):
    """Create a checkpoint for an agent."""
    afs = _get_afs(db)
    try:
        cp_id = afs.checkpoint(agent_id, label=label)
        if _json_out(ctx, {"checkpoint_id": cp_id, "agent_id": agent_id, "label": label}):
            return
        console.print(f"[green]Checkpoint created:[/green] {cp_id}")
        if label:
            console.print(f"  Label: {label}")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--checkpoint", "checkpoint_id", required=True, help="Checkpoint ID to restore")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def restore(agent_id: str, checkpoint_id: str, db: str):
    """Restore an agent to a previous checkpoint."""
    afs = _get_afs(db)
    try:
        afs.restore(agent_id, checkpoint_id)
        console.print(f"[green]Agent {agent_id} restored to checkpoint {checkpoint_id}[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--from", "from_cp", required=True, help="Source checkpoint ID")
@click.option("--to", "to_cp", required=True, help="Target checkpoint ID")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def diff(ctx, agent_id: str, from_cp: str, to_cp: str, db: str):
    """Compare two checkpoints of an agent."""
    from bene.cli.diff import render_diff

    afs = _get_afs(db)
    try:
        result = afs.diff_checkpoints(agent_id, from_cp, to_cp)
        if _json_out(ctx, result):
            return
        render_diff(result, console)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def checkpoints(ctx, agent_id: str, db: str):
    """List all checkpoints for an agent."""
    afs = _get_afs(db)
    cps = afs.list_checkpoints(agent_id)

    if _json_out(ctx, cps):
        afs.close()
        return

    if not cps:
        console.print("[dim]No checkpoints found[/dim]")
        return

    table = Table(title=f"Checkpoints for {agent_id[:12]}...")
    table.add_column("ID", style="cyan", max_width=14)
    table.add_column("Label")
    table.add_column("Created")
    table.add_column("Event ID", justify="right")

    for cp in cps:
        table.add_row(
            cp["checkpoint_id"][:12] + "...",
            cp.get("label") or "-",
            cp["created_at"][:19],
            str(cp.get("event_id") or "-"),
        )

    console.print(table)
    afs.close()


@cli.command("export")
@click.argument("agent_id")
@click.option("-o", "--output", required=True, help="Output file path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def export_agent(agent_id: str, output: str, db: str):
    """Export an agent to a standalone database file."""
    import shutil
    import sqlite3

    afs = _get_afs(db)

    # Verify agent exists
    try:
        afs.status(agent_id)
    except ValueError:
        console.print(f"[red]Agent not found: {agent_id}[/red]")
        return

    # Create a new database with just this agent's data
    shutil.copy2(db, output)

    # Remove other agents from the copy
    export_conn = sqlite3.connect(output)
    other_agents = export_conn.execute(
        "SELECT agent_id FROM agents WHERE agent_id != ?", (agent_id,)
    ).fetchall()

    # Every agent-scoped table (a real, non-FTS table with an agent_id column),
    # discovered dynamically so a newly added table can't silently leak another
    # agent's rows into the snapshot — a hardcoded list rotted here (it missed
    # `memory` and `shared_log`). FTS shadow tables stay in sync via their AFTER
    # DELETE triggers on the base tables.
    all_tables = [
        r[0]
        for r in export_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    agent_tables = []
    for t in all_tables:
        if t == "agents" or "_fts" in t:
            continue
        cols = {c[1] for c in export_conn.execute(f"PRAGMA table_info('{t}')").fetchall()}
        if "agent_id" in cols:
            agent_tables.append(t)

    for (other_id,) in other_agents:
        for table in agent_tables:
            export_conn.execute(f"DELETE FROM {table} WHERE agent_id = ?", (other_id,))
        export_conn.execute("DELETE FROM agents WHERE agent_id = ?", (other_id,))

    # Clean up orphaned blobs
    export_conn.execute(
        "DELETE FROM blobs WHERE content_hash NOT IN (SELECT content_hash FROM files WHERE content_hash IS NOT NULL)"
    )
    # Commit the DELETEs before VACUUM — VACUUM cannot run inside the implicit
    # transaction the deletes opened, or sqlite raises "cannot VACUUM from
    # within a transaction".
    export_conn.commit()
    export_conn.execute("VACUUM")
    export_conn.close()

    console.print(f"[green]Exported agent {agent_id[:12]}... to {output}[/green]")
    afs.close()


@cli.command("import")
@click.argument("file_path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--merge/--replace", default=True, help="Merge or replace existing data")
def import_agent(file_path: str, db: str, merge: bool):
    """Import an agent from a standalone database file."""
    import sqlite3

    if not Path(file_path).exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    afs = _get_afs(db)
    source = sqlite3.connect(file_path)

    agents = source.execute("SELECT agent_id, name FROM agents").fetchall()
    for agent_id, name in agents:
        console.print(f"[cyan]Importing agent:[/cyan] {agent_id[:12]}... ({name})")

    # Attach source database
    afs.conn.execute(f"ATTACH DATABASE '{file_path}' AS import_db")

    try:
        for table in ("agents", "blobs", "files", "tool_calls", "state", "events", "checkpoints"):
            afs.conn.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM import_db.{table}")
        afs.conn.commit()
        console.print(f"[green]Import complete — {len(agents)} agent(s) imported[/green]")
    except Exception as e:
        console.print(f"[red]Import failed: {e}[/red]")
    finally:
        afs.conn.execute("DETACH DATABASE import_db")
        source.close()
        afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--port", default=3100, help="MCP server port")
@click.option("--host", default="127.0.0.1", help="MCP server host")
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]), help="Transport")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
def serve(db: str, port: int, host: str, transport: str, config_file: str):
    """Start the BENE MCP server."""
    from bene.ccr.runner import ClaudeCodeRunner
    from bene.mcp.server import init_server
    from bene.router.tier import TierRouter

    afs = _get_afs(db)

    # Try config file first, then fall back to claude_code provider (no API key needed)
    _cfg_paths = [config_file, os.environ.get("BENE_CONFIG", ""), "./bene.yaml"]
    _loaded = False
    for _cfg in _cfg_paths:
        if _cfg and Path(_cfg).exists():
            config = load_config(_cfg)
            router = TierRouter.from_config(_cfg)
            _loaded = True
            break

    if not _loaded:
        # Default: use claude_code provider (Claude Code subscription, no API key)
        from bene.router.tier import ModelConfig
        from bene.router.providers import ClaudeCodeProvider

        _provider = ClaudeCodeProvider(model_id="claude-sonnet-4-6")
        from bene.router.tier import TierRouter as _GR

        router = _GR(
            models={
                "claude-sonnet": ModelConfig(
                    name="claude-sonnet",
                    provider="claude_code",
                    model_id="claude-sonnet-4-6",
                    use_for=["trivial", "moderate", "complex", "critical"],
                )
            },
        )
        # Inject the provider directly since TierRouter.__init__ creates it from config
        router.clients["claude-sonnet"] = _provider

    ccr = ClaudeCodeRunner(afs, router, **runner_kwargs_from_config(config if _loaded else {}))
    mcp_server = init_server(afs, ccr)

    if transport == "stdio":
        # The MCP protocol uses stdout for JSON-RPC responses.
        # But stray print() calls and library logging also go to stdout,
        # corrupting the protocol. Fix: redirect sys.stdout to stderr
        # for all Python code, but pass the ORIGINAL stdout to
        # stdio_server so MCP responses go to the right place.
        _original_stdout = sys.stdout
        sys.stdout = sys.stderr
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
        asyncio.run(_run_stdio(mcp_server, _original_stdout))
    else:
        console.print(f"[cyan]Listening on {host}:{port}[/cyan]")
        asyncio.run(_run_sse(mcp_server, host, port))


async def _run_stdio(mcp_server, original_stdout=None):
    from mcp.server.stdio import stdio_server

    # If we redirected sys.stdout, temporarily restore it so
    # stdio_server() binds to the real stdout file descriptor.
    if original_stdout:
        saved = sys.stdout
        sys.stdout = original_stdout
    async with stdio_server() as (read, write):
        if original_stdout:
            sys.stdout = saved  # re-redirect after binding
        await mcp_server.run(read, write, mcp_server.create_initialization_options())


async def _run_sse(mcp_server, host: str, port: int):
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
        ]
    )

    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def dashboard(db: str):
    """Launch the TUI dashboard for real-time agent monitoring."""
    from bene.cli.dashboard import BeneDashboard

    afs = _get_afs(db)
    app = BeneDashboard(afs)
    app.run()
    afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--port", default=8765, help="UI server port")
@click.option("--host", default="127.0.0.1", help="UI server host")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
def ui(db: str, port: int, host: str, no_browser: bool):
    """Launch the web UI dashboard (agent graph, events, tool calls)."""
    import threading
    import time as _time
    from bene.ui.server import run as _run_ui

    db_abs = str(Path(db).resolve())

    if not no_browser:

        def _open():
            _time.sleep(1.2)
            import webbrowser

            webbrowser.open(f"http://{host}:{port}/?db={db_abs}")

        threading.Thread(target=_open, daemon=True).start()

    console.print(
        f"[bold cyan]BENE UI[/bold cyan]  →  [link=http://{host}:{port}/?db={db_abs}]http://{host}:{port}/[/link]"
    )
    console.print(f"[dim]Project: {db_abs}[/dim]")
    console.print("[dim]Ctrl+C to stop[/dim]")
    try:
        _run_ui(host=host, port=port, db=db_abs)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


@cli.command()
@click.option("--port", default=8765, help="UI server port")
@click.option("--host", default="127.0.0.1", help="UI server host")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
@click.option(
    "--no-ui",
    is_flag=True,
    default=False,
    help="Run the kernel story and exit without starting the dashboard (CI-friendly)",
)
def demo(port: int, host: str, no_browser: bool, no_ui: bool):
    """Seed a demo database and open the live dashboard.

    Stage 1 (always): the BENE 2.0 kernel story — engrams, a falsifiable
    probe, one offline evolution round, memory consolidation, a trust
    report, and the senses manifest. Keyless, <60s.
    Stage 2 (unless --no-ui): seed richer demo data and open the dashboard.
    """
    if no_ui:
        _kernel_story()
        return
    _kernel_story()
    import random
    import threading
    import time as _time
    from bene.ui.server import run as _run_ui

    demo_db = str(Path("./demo.db").resolve())

    # ── Seed demo data ────────────────────────────────────────────────────
    console.print("[bold cyan]BENE Demo[/bold cyan]  Seeding demo.db…")

    if Path(demo_db).exists():
        try:
            Path(demo_db).unlink()
        except PermissionError:
            # File locked (old server still running) — use a timestamped name
            import time as _ts

            demo_db = str(Path(f"./demo_{int(_ts.time())}.db").resolve())

    db_obj = Bene(db_path=demo_db)

    waves = [
        {
            "goal": "Code review swarm: security + perf + style analysis of payments module",
            "agents": [
                (
                    "security-reviewer",
                    "completed",
                    4,
                    18,
                    "Scan payments module for SQL injection, auth bypass, and hardcoded secrets",
                ),
                (
                    "perf-reviewer",
                    "completed",
                    3,
                    12,
                    "Profile payments module for N+1 queries, missing indexes, and slow loops",
                ),
                (
                    "style-reviewer",
                    "completed",
                    3,
                    10,
                    "Enforce PEP 8, naming conventions, and docstring coverage",
                ),
                (
                    "test-writer",
                    "completed",
                    5,
                    22,
                    "Write pytest unit tests for all payment endpoints",
                ),
                (
                    "doc-writer",
                    "completed",
                    4,
                    8,
                    "Generate API reference docs from code and write usage examples",
                ),
            ],
        },
        {
            "goal": "Parallel refactor: auth module + legacy parser + API redesign",
            "agents": [
                (
                    "auth-refactor",
                    "completed",
                    6,
                    28,
                    "Refactor auth.py to use JWT tokens, remove session-based auth",
                ),
                (
                    "legacy-parser",
                    "failed",
                    2,
                    9,
                    "Parse legacy CSV format and migrate to Parquet — fails on encoding edge cases",
                ),
                (
                    "api-redesign",
                    "running",
                    4,
                    20,
                    "Redesign REST API to follow OpenAPI 3.1 spec with versioned endpoints",
                ),
                (
                    "migration-agent",
                    "running",
                    3,
                    15,
                    "Run database migration: add user_preferences table, backfill defaults",
                ),
            ],
        },
        {
            "goal": "Post-deploy triage: investigate prod anomaly in checkout flow",
            "agents": [
                (
                    "log-analyst",
                    "completed",
                    2,
                    6,
                    "Parse production logs from last 2 hours, find spike in 500 errors",
                ),
                (
                    "runaway-agent",
                    "killed",
                    1,
                    5,
                    "Attempt auto-rollback — terminated after exceeding 30-minute budget",
                ),
                (
                    "data-pipeline",
                    "paused",
                    3,
                    11,
                    "Backfill missing orders from cache into PostgreSQL — paused awaiting approval",
                ),
            ],
        },
    ]

    tool_names = [
        "fs_read",
        "fs_write",
        "fs_ls",
        "shell_exec",
        "state_set",
        "state_get",
        "fs_mkdir",
    ]
    total_agents = 0

    for wave in waves:
        for agent_tuple in wave["agents"]:
            name = cast(str, agent_tuple[0])
            target_status = cast(str, agent_tuple[1])
            num_files = cast(int, agent_tuple[2])
            num_calls = cast(int, agent_tuple[3])
            task = cast(str, agent_tuple[4])
            aid = db_obj.spawn(name)
            db_obj.set_state(aid, "task", task)

            db_obj.write(aid, "/src/main.py", f"# {name}\n\ndef main():\n    pass\n".encode())
            db_obj.write(aid, "/README.md", f"# {name}\n\n{task}\n".encode())
            if "reviewer" in name:
                db_obj.write(
                    aid,
                    "/review.md",
                    f"# Review by {name}\n\n## Findings\n- Issue 1: SQL injection risk\n".encode(),
                )
            if "test" in name:
                db_obj.write(
                    aid,
                    "/tests/test_main.py",
                    b"import pytest\n\ndef test_basic():\n    assert True\n",
                )
            for i in range(max(0, num_files - 2)):
                db_obj.write(aid, f"/src/module_{i}.py", f"# module {i}\n".encode())

            db_obj.set_state(
                aid, "progress", 100 if target_status == "completed" else random.randint(15, 70)
            )
            db_obj.set_state(aid, "iteration", random.randint(5, 50))

            for i in range(num_calls):
                tool = random.choice(tool_names)
                call_id = db_obj.log_tool_call(aid, tool, {"path": f"/src/file_{i}.py"})
                db_obj.start_tool_call(call_id)
                if target_status == "failed" and i >= num_calls - 2:
                    db_obj.complete_tool_call(
                        call_id,
                        {"error": "ConnectionError"},
                        status="error",
                        error_message="ConnectionError",
                        token_count=random.randint(50, 300),
                    )
                else:
                    db_obj.complete_tool_call(
                        call_id,
                        {"result": "ok"},
                        status="success",
                        token_count=random.randint(400, 4500),
                    )

            db_obj.checkpoint(aid, label=f"{name}-initial")
            if target_status == "completed":
                db_obj.checkpoint(aid, label=f"{name}-final")
                db_obj.complete(aid)
            elif target_status == "running":
                db_obj.set_status(aid, "running", pid=12345)
                db_obj.heartbeat(aid)
            elif target_status == "failed":
                db_obj.fail(aid, error="ConnectionError: endpoint unreachable")
            elif target_status == "killed":
                db_obj.kill(aid)
            elif target_status == "paused":
                db_obj.set_status(aid, "running", pid=12345)
                db_obj.pause(aid)

            total_agents += 1

    db_obj.close()
    console.print(
        f"[green]✓[/green] Seeded {total_agents} agents across {len(waves)} execution waves"
    )

    # ── Open UI ───────────────────────────────────────────────────────────
    if not no_browser:

        def _open():
            _time.sleep(1.2)
            import webbrowser

            webbrowser.open(f"http://{host}:{port}/?db={demo_db}")

        threading.Thread(target=_open, daemon=True).start()

    console.print(
        f"[bold cyan]Dashboard[/bold cyan]  →  [link=http://{host}:{port}/]http://{host}:{port}/[/link]"
    )
    console.print("[dim]Ctrl+C to stop[/dim]\n")
    try:
        _run_ui(host=host, port=port, db=demo_db)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def kill(ctx, agent_id: str, db: str):
    """Kill a running agent."""
    afs = _get_afs(db)
    try:
        afs.kill(agent_id)
        if _json_out(ctx, {"agent_id": agent_id, "status": "killed"}):
            return
        console.print(f"[red]Agent {agent_id[:12]}... killed[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def status(ctx, agent_id: str, db: str):
    """Get detailed status of an agent."""
    afs = _get_afs(db)
    try:
        info = afs.status(agent_id)
        if _json_out(ctx, info):
            return
        console.print_json(json.dumps(info, indent=2))
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("read")
@click.argument("agent_id")
@click.argument("path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def read_file(ctx, agent_id: str, path: str, db: str):
    """Read a file from an agent's virtual filesystem."""
    afs = _get_afs(db)
    try:
        content = afs.read(agent_id, path)
        text = content.decode("utf-8", errors="replace")
        if ctx.obj.get("json"):
            click.echo(json.dumps({"agent_id": agent_id, "path": path, "content": text}))
        else:
            click.echo(text)
    except FileNotFoundError:
        if not _json_err(ctx, f"File not found: {agent_id}:{path}"):
            console.print(f"[red]File not found: {agent_id}:{path}[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("logs")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--tail", "-n", type=int, help="Show last N events")
@click.pass_context
def logs(ctx, agent_id: str, db: str, tail: int):
    """View an agent's conversation history and event log."""
    afs = _get_afs(db)
    try:
        # Try conversation first
        conversation = afs.get_state_or(agent_id, "conversation")
        events = afs.query(
            "SELECT timestamp, event_type, payload FROM events "
            "WHERE agent_id = ? ORDER BY timestamp",
            (agent_id,),
        )
        if tail:
            events = events[-tail:]

        result = {
            "agent_id": agent_id,
            "conversation_turns": len(conversation) if conversation else 0,
            "events": events,
        }
        if conversation:
            result["conversation"] = conversation

        if _json_out(ctx, result):
            return

        # Pretty print
        info = afs.status(agent_id)
        console.print(f"[bold]{info['name']}[/bold] [{info['status']}]")
        if conversation:
            console.print(f"\n[cyan]Conversation ({len(conversation)} turns):[/cyan]")
            for msg in conversation:
                role = msg.get("role", "?")
                content = str(msg.get("content", ""))[:200]
                console.print(f"  [{role}] {content}")
        console.print(f"\n[cyan]Events ({len(events)}):[/cyan]")
        for evt in events[-20:]:
            console.print(f"  {evt['timestamp'][:19]} {evt['event_type']}")
        if len(events) > 20:
            console.print(f"  ... ({len(events) - 20} more, use --json for all)")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("index")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def build_index(ctx, agent_id: str, db: str):
    """Build an /index.md for an agent's VFS."""
    afs = _get_afs(db)
    try:
        content = afs.build_index(agent_id)
        if ctx.obj.get("json"):
            click.echo(json.dumps({"agent_id": agent_id, "index": content}))
        else:
            console.print(content)
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("search")
@click.argument("query_text")
@click.option("--agent", "-a", help="Scope to one agent")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--limit", "-n", default=50, help="Max results")
@click.pass_context
def search_files(ctx, query_text: str, agent: str, db: str, limit: int):
    """Full-text search across agent VFS file contents."""
    afs = _get_afs(db)
    try:
        results = afs.search(query_text, agent_id=agent, limit=limit)
        if _json_out(ctx, results):
            return
        if not results:
            console.print("[dim]No matches[/dim]")
            return
        from rich.table import Table as _T

        table = _T(title=f"Search: {query_text}")
        table.add_column("Agent", style="cyan", max_width=14)
        table.add_column("Path")
        table.add_column("Line", justify="right")
        table.add_column("Content", max_width=60)
        for r in results:
            table.add_row(r["agent_id"][:12] + "...", r["path"], str(r["line"]), r["content"][:60])
        console.print(table)
    finally:
        afs.close()


# ── Meta-Harness Commands ────────────────────────────────────────


@cli.group()
def mh():
    """Meta-Harness — automated harness optimization."""
    pass


@mh.command("search")
@click.option(
    "--benchmark",
    "-b",
    required=True,
    type=click.Choice(["text_classify", "math_rag", "agentic_coding"]),
    help="Benchmark to optimize for",
)
@click.option("--iterations", "-n", default=20, help="Number of search iterations")
@click.option("--candidates", "-k", default=3, help="Candidates per iteration")
@click.option("--seed", "-s", multiple=True, help="Seed harness file paths")
@click.option("--proposer-model", help="Force model for proposer agent")
@click.option("--eval-model", help="Force model for evaluation")
@click.option("--max-parallel", default=4, help="Max parallel evaluations")
@click.option("--eval-subset", type=int, help="Subsample problems for faster search")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option("--background/--foreground", default=False, help="Run as detached background process")
@click.option(
    "--dry-run", is_flag=True, default=False, help="Evaluate seeds only, report baseline scores"
)
@click.pass_context
def mh_search(
    ctx,
    benchmark,
    iterations,
    candidates,
    seed,
    proposer_model,
    eval_model,
    max_parallel,
    eval_subset,
    db,
    config_file,
    background,
    dry_run,
):
    """Run a meta-harness search to optimize a harness for a benchmark."""
    import subprocess as _sp

    if not Path(config_file).exists():
        if not _json_err(ctx, f"Config file not found: {config_file}"):
            console.print(f"[red]Config file not found:[/red] {config_file}")
        return

    if background:
        # Launch as detached worker process
        cmd = [
            sys.executable,
            "-m",
            "bene.metaharness.worker",
            "--db",
            db,
            "--config-file",
            config_file,
            "--benchmark",
            benchmark,
            "--iterations",
            str(iterations),
            "--candidates",
            str(candidates),
            "--max-parallel",
            str(max_parallel),
        ]
        if eval_subset:
            cmd += ["--eval-subset", str(eval_subset)]
        if proposer_model:
            cmd += ["--proposer-model", proposer_model]
        for s in seed:
            cmd += ["--seed", s]

        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True

        import time as _time

        log_path = os.path.join(
            os.path.dirname(os.path.abspath(db)), f"bene-worker-{int(_time.time())}.log"
        )
        log_file = open(log_path, "w")
        proc = _sp.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)

        result = {
            "status": "running",
            "pid": proc.pid,
            "log_path": log_path,
            "message": f"Worker launched (PID {proc.pid}). Log: {log_path}",
        }
        if _json_out(ctx, result):
            return
        console.print(f"[green]Worker launched[/green] (PID {proc.pid})")
        console.print(f"  Log: {log_path}")
        console.print("  Poll with: bene mh status <search_agent_id>")
        return

    # Foreground mode — run in-process
    from bene.metaharness.search import MetaHarnessSearch
    from bene.metaharness.harness import SearchConfig
    from bene.metaharness.benchmarks import get_benchmark
    from bene.router.tier import TierRouter
    import bene.metaharness.benchmarks.text_classify  # noqa: F401
    import bene.metaharness.benchmarks.math_rag  # noqa: F401
    import bene.metaharness.benchmarks.agentic_coding  # noqa: F401

    afs = _get_afs(db)
    router = TierRouter.from_config(config_file)

    config = SearchConfig(
        benchmark=benchmark,
        max_iterations=iterations,
        candidates_per_iteration=candidates,
        seed_harnesses=list(seed),
        proposer_model=proposer_model,
        evaluator_model=eval_model,
        max_parallel_evals=max_parallel,
        eval_subset_size=eval_subset,
    )

    bench = get_benchmark(benchmark)

    if not ctx.obj.get("json"):
        console.print("[cyan]Starting meta-harness search[/cyan]")
        console.print(f"  Benchmark: {benchmark}")
        console.print(f"  Iterations: {iterations}")
        console.print(f"  Candidates/iter: {candidates}")
        console.print(f"  Max parallel: {max_parallel}")

    search = MetaHarnessSearch(afs, router, bench, config)
    if ctx.params.get("dry_run"):
        if not ctx.obj.get("json"):
            console.print("[cyan]Dry-run: evaluating seeds only[/cyan]")
        result = asyncio.run(search.run_seeds_only())
    else:
        result = asyncio.run(search.run())

    result_data = {
        "search_agent_id": result.search_agent_id,
        "status": "completed",
        "summary": result.summary(),
        "total_harnesses": result.total_harnesses_evaluated,
        "duration_seconds": round(result.total_duration_seconds, 1),
        "frontier_size": len(result.frontier.points),
    }
    if not _json_out(ctx, result_data):
        console.print(f"\n[green]{result.summary()}[/green]")
    afs.close()


@mh.command("frontier")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_frontier(ctx, search_agent_id, db):
    """Show the Pareto frontier of a meta-harness search."""
    afs = _get_afs(db)
    try:
        data = afs.read(search_agent_id, "/pareto/frontier.json")
        frontier = json.loads(data)

        if _json_out(ctx, frontier):
            return

        table = Table(title="Pareto Frontier")
        table.add_column("Harness ID", style="cyan", max_width=16)
        table.add_column("Iteration", justify="right")
        for obj in frontier.get("objectives", {}):
            table.add_column(obj.capitalize(), justify="right")

        for point in frontier.get("points", []):
            row = [point["harness_id"][:14] + "...", str(point.get("iteration", "?"))]
            for obj in frontier.get("objectives", {}):
                val = point.get("scores", {}).get(obj, 0)
                row.append(f"{val:.4f}")
            table.add_row(*row)

        console.print(table)
    except FileNotFoundError:
        if not _json_err(ctx, "No frontier found"):
            console.print("[red]No frontier found. Is this a valid search agent?[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("inspect")
@click.argument("search_agent_id")
@click.argument("harness_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def mh_inspect(search_agent_id, harness_id, db):
    """Inspect a specific harness — source, scores, and trace summary."""
    afs = _get_afs(db)
    try:
        base = f"/harnesses/{harness_id}"

        # Source
        source = afs.read(search_agent_id, f"{base}/source.py").decode()
        console.print("[bold]Source Code:[/bold]")
        console.print(source)

        # Scores
        scores = json.loads(afs.read(search_agent_id, f"{base}/scores.json"))
        console.print("\n[bold]Scores:[/bold]")
        for k, v in scores.items():
            console.print(f"  {k}: {v:.4f}")

        # Metadata
        meta = json.loads(afs.read(search_agent_id, f"{base}/metadata.json"))
        console.print("\n[bold]Metadata:[/bold]")
        console.print(f"  Iteration: {meta.get('iteration', '?')}")
        console.print(f"  Parents: {meta.get('parent_ids', [])}")
        console.print(f"  Duration: {meta.get('duration_ms', 0)}ms")
        if meta.get("metadata", {}).get("rationale"):
            console.print(f"  Rationale: {meta['metadata']['rationale'][:200]}")

        # Trace summary
        try:
            trace_data = afs.read(search_agent_id, f"{base}/trace.jsonl").decode()
            lines = [trace_line for trace_line in trace_data.split("\n") if trace_line.strip()]
            console.print(f"\n[bold]Trace:[/bold] {len(lines)} entries")
            for line in lines[:10]:
                entry = json.loads(line)
                console.print(f"  {entry.get('type', '?')}: {str(entry)[:80]}")
            if len(lines) > 10:
                console.print(f"  ... and {len(lines) - 10} more")
        except FileNotFoundError:
            console.print("\n[dim]No trace available[/dim]")

    except FileNotFoundError as e:
        console.print(f"[red]Not found: {e}[/red]")
    finally:
        afs.close()


@mh.command("status")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_status(ctx, search_agent_id, db):
    """Show the status of a meta-harness search."""
    afs = _get_afs(db)
    try:
        info = afs.status(search_agent_id)
        iteration = afs.get_state_or(search_agent_id, "current_iteration", 0)
        harnesses = afs.ls(search_agent_id, "/harnesses")

        result = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "pid": info.get("pid"),
            "current_iteration": iteration,
            "harnesses_evaluated": len(harnesses),
        }

        try:
            frontier = json.loads(afs.read(search_agent_id, "/pareto/frontier.json"))
            result["frontier_size"] = len(frontier.get("points", []))
        except FileNotFoundError:
            result["frontier_size"] = 0

        if _json_out(ctx, result):
            return

        console.print(f"[bold]Search Agent:[/bold] {search_agent_id[:14]}...")
        console.print(f"  Status: {info['status']}")
        console.print(f"  Current iteration: {iteration}")
        console.print(f"  Harnesses evaluated: {len(harnesses)}")
        console.print(f"  Frontier size: {result['frontier_size']}")

    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("resume")
@click.argument("search_agent_id")
@click.option(
    "--benchmark", "-b", required=True, help="Benchmark name (must match original search)"
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
def mh_resume(search_agent_id, benchmark, db, config_file):
    """Resume an interrupted meta-harness search from its last iteration."""
    from bene.metaharness.search import MetaHarnessSearch
    from bene.metaharness.harness import SearchConfig
    from bene.metaharness.benchmarks import get_benchmark
    from bene.router.tier import TierRouter
    import bene.metaharness.benchmarks.text_classify  # noqa: F401
    import bene.metaharness.benchmarks.math_rag  # noqa: F401
    import bene.metaharness.benchmarks.agentic_coding  # noqa: F401
    import bene.metaharness.benchmarks.paper_datasets  # noqa: F401

    afs = _get_afs(db)

    if not Path(config_file).exists():
        console.print(f"[red]Config file not found:[/red] {config_file}")
        return

    router = TierRouter.from_config(config_file)
    bench = get_benchmark(benchmark)
    config = SearchConfig(benchmark=benchmark)
    search = MetaHarnessSearch(afs, router, bench, config)

    console.print(f"[cyan]Resuming search {search_agent_id[:14]}...[/cyan]")

    result = asyncio.run(search.resume(search_agent_id))

    console.print(f"\n[green]{result.summary()}[/green]")
    afs.close()


@mh.command("lint")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_lint(ctx, search_agent_id, db):
    """Health-check a search archive for issues."""
    afs = _get_afs(db)
    try:
        info = afs.status(search_agent_id)
        harness_dirs = afs.ls(search_agent_id, "/harnesses")
        issues_found = []

        # Check for harnesses with empty scores
        empty_scores = 0
        failed_harnesses = 0
        all_scores = {}
        for entry in harness_dirs:
            if not entry.get("is_dir"):
                continue
            hid = entry["name"]
            try:
                scores = json.loads(
                    afs.read(search_agent_id, f"/harnesses/{hid}/scores.json").decode()
                )
                meta = json.loads(
                    afs.read(search_agent_id, f"/harnesses/{hid}/metadata.json").decode()
                )
                if not scores:
                    empty_scores += 1
                if meta.get("error"):
                    failed_harnesses += 1
                all_scores[hid] = scores
            except FileNotFoundError:
                issues_found.append(f"Missing scores/metadata for harness {hid[:12]}")

        if empty_scores:
            issues_found.append(f"{empty_scores} harnesses have empty scores (evaluation failed)")
        if failed_harnesses:
            issues_found.append(f"{failed_harnesses} harnesses have errors in metadata")

        # Check for iteration errors
        iter_dirs = afs.ls(search_agent_id, "/iterations")
        error_iters = 0
        for entry in iter_dirs:
            if entry.get("is_dir"):
                try:
                    afs.read(search_agent_id, f"{entry['path']}/error.json")
                    error_iters += 1
                except FileNotFoundError:
                    pass
        if error_iters:
            issues_found.append(
                f"{error_iters} iterations had errors (proposer timeout or eval failure)"
            )

        # Check frontier
        try:
            frontier = json.loads(afs.read(search_agent_id, "/pareto/frontier.json").decode())
            frontier_size = len(frontier.get("points", []))
            if frontier_size == 0:
                issues_found.append("Pareto frontier is empty — no successful harnesses")
        except FileNotFoundError:
            issues_found.append("No Pareto frontier found")
            frontier_size = 0

        result = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "total_harnesses": len(harness_dirs),
            "frontier_size": frontier_size,
            "issues": issues_found,
            "health": "clean" if not issues_found else f"{len(issues_found)} issues",
        }
        if _json_out(ctx, result):
            return

        console.print(f"[bold]Lint: {search_agent_id[:14]}...[/bold]")
        console.print(f"  Status: {info['status']}")
        console.print(f"  Harnesses: {len(harness_dirs)}, Frontier: {frontier_size}")
        if issues_found:
            console.print(f"\n[yellow]{len(issues_found)} issues found:[/yellow]")
            for issue in issues_found:
                console.print(f"  - {issue}")
        else:
            console.print("\n[green]Clean — no issues found[/green]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("knowledge")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_knowledge(ctx, db):
    """Show the persistent knowledge base — discoveries from all prior searches."""
    afs = _get_afs(db)
    try:
        knowledge_id = afs.get_or_create_singleton(
            "bene-knowledge",
            aliases=("bene-knowledge",),
        )
        files = (
            afs.ls(knowledge_id, "/discoveries") if afs.exists(knowledge_id, "/discoveries") else []
        )

        benchmarks = []
        for entry in files:
            if entry.get("is_dir"):
                bname = entry["name"]
                try:
                    latest = json.loads(
                        afs.read(knowledge_id, f"/discoveries/{bname}/latest_search.json").decode()
                    )
                except FileNotFoundError:
                    latest = {}
                harnesses = (
                    afs.ls(knowledge_id, f"/discoveries/{bname}/harnesses")
                    if afs.exists(knowledge_id, f"/discoveries/{bname}/harnesses")
                    else []
                )
                benchmarks.append(
                    {
                        "benchmark": bname,
                        "harnesses_stored": len(harnesses),
                        "latest_search": latest,
                    }
                )

        result = {"knowledge_agent_id": knowledge_id, "benchmarks": benchmarks}
        if _json_out(ctx, result):
            return

        console.print(f"[bold]Knowledge Agent:[/bold] {knowledge_id[:14]}...")
        if not benchmarks:
            console.print("[dim]No discoveries yet — run a search first[/dim]")
        for b in benchmarks:
            console.print(f"\n  [cyan]{b['benchmark']}[/cyan]")
            console.print(f"    Harnesses stored: {b['harnesses_stored']}")
            if b["latest_search"]:
                console.print(f"    Best scores: {b['latest_search'].get('best_scores', {})}")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


# ── Memory CLI (bene memory ...) ──────────────────────────────────────────


@cli.group()
def memory():
    """Cross-agent memory store — write and search shared knowledge."""


@memory.command("write")
@click.argument("agent_id")
@click.argument("content")
@click.option(
    "--type",
    "-t",
    "mem_type",
    default="observation",
    type=click.Choice(["observation", "result", "skill", "insight", "error"]),
    help="Memory type",
)
@click.option("--key", "-k", default=None, help="Optional human-readable key")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_write(ctx, agent_id: str, content: str, mem_type: str, key: str, db: str):
    """Write a memory entry for AGENT_ID with CONTENT."""
    from bene.memory import MemoryStore

    import sqlite3

    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        try:
            mid = mem.write(agent_id=agent_id, content=content, type=mem_type, key=key)
        except sqlite3.IntegrityError:
            msg = f"FOREIGN KEY constraint failed: agent '{agent_id}' does not exist."
            if not _json_err(ctx, msg):
                console.print(f"[red]Error:[/red] {msg}")
                sys.exit(1)
            return
        result = {"memory_id": mid, "agent_id": agent_id, "type": mem_type, "key": key}
        if _json_out(ctx, result):
            return
        console.print(
            f"[green]Memory #{mid} written[/green]  agent={agent_id[:14]}  type={mem_type}"
            + (f"  key={key}" if key else "")
        )
    finally:
        afs.close()


@memory.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option(
    "--type",
    "-t",
    "mem_type",
    default=None,
    type=click.Choice(["observation", "result", "skill", "insight", "error"]),
    help="Filter by type",
)
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_search(ctx, query: str, limit: int, mem_type: str, agent: str, db: str):
    """Full-text search across shared memory (FTS5 + porter stemming)."""
    from bene.memory import MemoryStore

    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        hits = mem.search(query=query, limit=limit, type=mem_type, agent_id=agent)
        if _json_out(ctx, [h.to_dict() for h in hits]):
            return
        if not hits:
            console.print("[dim]No results[/dim]")
            return
        for h in hits:
            key_str = f"  [dim]key={h.key}[/dim]" if h.key else ""
            console.print(
                f"[bold cyan]#{h.memory_id}[/bold cyan]  "
                f"[yellow]{h.type}[/yellow]  "
                f"[dim]{h.agent_id[:14]}[/dim]  "
                f"[dim]{h.created_at[:19]}[/dim]{key_str}"
            )
            console.print(f"  {h.content[:120]}" + ("..." if len(h.content) > 120 else ""))
    finally:
        afs.close()


@memory.command("ls")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option(
    "--type",
    "-t",
    "mem_type",
    default=None,
    type=click.Choice(["observation", "result", "skill", "insight", "error"]),
    help="Filter by type",
)
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_ls(ctx, agent: str, mem_type: str, limit: int, db: str):
    """List memory entries (most recent first)."""
    from bene.memory import MemoryStore

    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        entries = mem.list(agent_id=agent, type=mem_type, limit=limit)
        if _json_out(ctx, [e.to_dict() for e in entries]):
            return
        stats = mem.stats()
        console.print(
            f"[bold]Memory Store[/bold]  total={stats['total']}  "
            + "  ".join(f"{k}={v}" for k, v in stats["by_type"].items())
        )
        if not entries:
            console.print("[dim]No entries[/dim]")
            return
        for e in entries:
            key_str = f"  [dim]{e.key}[/dim]" if e.key else ""
            console.print(
                f"  [cyan]#{e.memory_id}[/cyan]  [yellow]{e.type}[/yellow]  "
                f"[dim]{e.agent_id[:14]}[/dim]  [dim]{e.created_at[:19]}[/dim]{key_str}"
            )
            console.print(f"    {e.content[:100]}" + ("..." if len(e.content) > 100 else ""))
    finally:
        afs.close()


@memory.command("rehighlight")
@click.argument("agent_id")
@click.option("--window", default=30, help="Recent context items to consider")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_rehighlight(ctx, agent_id: str, window: int, db: str):
    """Re-highlight in-context evidence matching the agent's consolidated intent.

    The VEA rung of the recovery ladder: foreground the evidence already present,
    dim the rest, before paying for a re-retrieval or checkpoint restore.
    `evidence_present=false` is the signal to escalate instead.
    """
    from bene.kernel.memory import PollutionDetector

    _, store = _kernel_stores(db)
    rctx = PollutionDetector(store).rehighlight(agent_id, window=window)
    data = {"agent_id": agent_id, **rctx.manifest}
    if _json_out(ctx, data):
        return
    console.print(
        f"[bold]rehighlight[/bold] {agent_id}  "
        f"evidence_present=[{'green' if rctx.evidence_present else 'red'}]{rctx.evidence_present}[/]"
    )
    console.print(f"  terms: [dim]{', '.join(rctx.terms) or '(none)'}[/dim]")
    for i in rctx.foregrounded:
        console.print(f"  [green]«fg» {i.get('evidence_score')}[/green]  {i.get('id')}")
    for i in rctx.dimmed:
        console.print(f"  [dim]·dim·       {i.get('id')}[/dim]")


# ── Shared Log CLI (bene log ...) ─────────────────────────────────────────


@cli.group("log")
def shared_log_group():
    """Shared coordination log — LogAct intent/vote/decide protocol."""


@shared_log_group.command("tail")
@click.option("--n", "-n", "count", default=20, help="Number of entries to show")
@click.option("--type", "-t", "log_type", default=None, help="Filter by entry type")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def log_tail(ctx, count: int, log_type: str, agent: str, db: str):
    """Show the last N entries from the shared coordination log."""
    from bene.shared_log import SharedLog

    afs = _get_afs(db)
    try:
        log = SharedLog(afs.conn)
        if log_type or agent:
            entries = log.read(type=log_type, agent_id=agent, limit=count)
        else:
            entries = log.tail(count)
        if _json_out(ctx, [e.to_dict() for e in entries]):
            return
        if not entries:
            console.print("[dim]Log is empty[/dim]")
            return
        TYPE_COLORS = {
            "intent": "cyan",
            "vote": "yellow",
            "decision": "green",
            "commit": "bold green",
            "result": "magenta",
            "abort": "red",
            "policy": "bold white",
            "mail": "blue",
        }
        for e in entries:
            color = TYPE_COLORS.get(e.type, "white")
            ref_str = f"  [dim]ref={e.ref_id}[/dim]" if e.ref_id else ""
            console.print(
                f"[dim]{e.position:4d}[/dim]  [{color}]{e.type:8s}[/{color}]  "
                f"[dim]{e.agent_id[:14]}[/dim]  [dim]{e.created_at[:19]}[/dim]{ref_str}"
            )
            payload_str = str(e.payload)
            console.print(f"       {payload_str[:100]}" + ("..." if len(payload_str) > 100 else ""))
    finally:
        afs.close()


@shared_log_group.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def log_ls(ctx, db: str):
    """Show shared log statistics."""
    from bene.shared_log import SharedLog

    afs = _get_afs(db)
    try:
        log = SharedLog(afs.conn)
        stats = log.stats()
        if _json_out(ctx, stats):
            return
        console.print(f"[bold]Shared Log[/bold]  total={stats['total']}")
        for t, n in stats["by_type"].items():
            console.print(f"  {t:12s} {n}")
    finally:
        afs.close()


# ── Skills CLI (bene skills ...) ──────────────────────────────────────────


@cli.group("skills")
def skills_group():
    """Cross-agent skill library — save and search reusable solution patterns."""


@skills_group.command("save")
@click.option("--name", "-n", required=True, help="Skill name (snake_case)")
@click.option("--description", "-d", required=True, help="What the skill does and when to use it")
@click.option("--template", "-t", required=True, help="Prompt template (use {param} for variables)")
@click.option("--agent", "-a", default=None, help="Source agent_id")
@click.option("--tags", default=None, help="Comma-separated tags (e.g. classification,ensemble)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_save(ctx, name: str, description: str, template: str, agent: str, tags: str, db: str):
    """Save a reusable skill to the shared library."""
    from bene.skills import SkillStore

    import sqlite3

    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        tag_list = [t.strip() for t in tags.split(",")] if tags else []
        try:
            sid = sk.save(
                name=name,
                description=description,
                template=template,
                source_agent_id=agent,
                tags=tag_list,
            )
        except sqlite3.IntegrityError:
            msg = f"FOREIGN KEY constraint failed: agent '{agent}' does not exist."
            if not _json_err(ctx, msg):
                console.print(f"[red]Error:[/red] {msg}")
                sys.exit(1)
            return
        skill = sk.get(sid)
        result = skill.to_dict() if skill else {"skill_id": sid}
        if _json_out(ctx, result):
            return
        params_str = ", ".join(skill.params()) if skill and skill.params() else "(no params)"
        console.print(f"[green]Skill #{sid} saved[/green]  name={name}  params=[{params_str}]")
        if tag_list:
            console.print(f"  tags: {', '.join(tag_list)}")
    finally:
        afs.close()


@skills_group.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--rank", default="bm25", type=click.Choice(["bm25", "weighted"]), help="Ranking")
@click.option(
    "--include-demoted", is_flag=True, default=False, help="Include demoted/retired skills"
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_search(ctx, query: str, limit: int, tag: str, rank: str, include_demoted: bool, db: str):
    """Full-text search across the skill library (FTS5 + BM25)."""
    from bene.skills import SkillStore

    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        hits = sk.search(
            query=query, limit=limit, tag=tag, rank=rank, include_demoted=include_demoted
        )
        if _json_out(ctx, [s.to_dict() for s in hits]):
            return
        if not hits:
            console.print("[dim]No skills found[/dim]")
            return
        for s in hits:
            rate = f"{s.success_count}/{s.use_count}" if s.use_count else "unused"
            tags_str = f"  [dim]{', '.join(s.tags)}[/dim]" if s.tags else ""
            console.print(
                f"[bold cyan]#{s.skill_id}[/bold cyan]  [yellow]{s.name}[/yellow]  "
                f"[dim]{rate}[/dim]{tags_str}"
            )
            console.print(f"  {s.description[:120]}" + ("..." if len(s.description) > 120 else ""))
            params = s.params()
            if params:
                console.print(f"  params: {{{', '.join(params)}}}")
    finally:
        afs.close()


@skills_group.command("ls")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--agent", "-a", default=None, help="Filter by source agent_id")
@click.option(
    "--order",
    default="created_at",
    type=click.Choice(["created_at", "success_count", "use_count", "name"]),
    help="Sort order",
)
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_ls(ctx, tag: str, agent: str, order: str, limit: int, db: str):
    """List skills in the library (most recent first)."""
    from bene.skills import SkillStore

    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        skills = sk.list(tag=tag, source_agent_id=agent, order_by=order, limit=limit)
        if _json_out(ctx, [s.to_dict() for s in skills]):
            return
        stats = sk.stats()
        console.print(f"[bold]Skill Library[/bold]  total={stats['total']}")
        if not skills:
            console.print("[dim]No skills[/dim]")
            return
        t = Table(show_header=True, header_style="bold")
        t.add_column("ID", style="cyan", width=5)
        t.add_column("Name", style="yellow", width=24)
        t.add_column("Tags", width=20)
        t.add_column("Used", width=6)
        t.add_column("OK%", width=6)
        t.add_column("Description", width=40)
        for s in skills:
            rate = f"{s.success_count / s.use_count * 100:.0f}%" if s.use_count else "-"
            t.add_row(
                str(s.skill_id),
                s.name,
                ", ".join(s.tags[:3]),
                str(s.use_count),
                rate,
                s.description[:40] + ("..." if len(s.description) > 40 else ""),
            )
        console.print(t)
    finally:
        afs.close()


@skills_group.command("apply")
@click.argument("skill_id", type=int)
@click.option(
    "--param",
    "-p",
    "params",
    multiple=True,
    help="Template param as key=value (repeat for multiple)",
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_apply(ctx, skill_id: int, params: tuple, db: str):
    """Render a skill template with parameters and print the result.

    Example: bene skills apply 3 -p model=gpt4 -p voting=majority
    """
    from bene.skills import SkillStore

    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        skill = sk.get(skill_id)
        if not skill:
            console.print(f"[red]Skill #{skill_id} not found[/red]")
            return
        kv: dict[str, str] = {}
        for p in params:
            if "=" in p:
                k, v = p.split("=", 1)
                kv[k.strip()] = v.strip()
        rendered = skill.apply(**kv)
        if _json_out(ctx, {"skill_id": skill_id, "name": skill.name, "rendered": rendered}):
            return
        console.print(f"[bold]Skill #{skill_id} — {skill.name}[/bold]")
        console.print(rendered)
    finally:
        afs.close()


@skills_group.command("delete")
@click.argument("skill_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_delete(ctx, skill_id: int, db: str):
    """Delete a skill by ID."""
    from bene.skills import SkillStore

    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        removed = sk.delete(skill_id)
        result = {"skill_id": skill_id, "deleted": removed}
        if _json_out(ctx, result):
            return
        if removed:
            console.print(f"[green]Skill #{skill_id} deleted[/green]")
        else:
            console.print(f"[yellow]Skill #{skill_id} not found[/yellow]")
    finally:
        afs.close()


@skills_group.group("plasticity")
def skills_plasticity():
    """Demote/retire failing skills (probe-gated; append-only audit trail)."""


@skills_plasticity.command("scan")
@click.option("--dry-run", is_flag=True, default=False, help="Report decisions, do not persist")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_plasticity_scan(ctx, dry_run: bool, db: str):
    """Scan skill telemetry; demote degraded skills, retire long-idle ones."""
    from bene.kernel.memory import PlasticityScanner

    afs, store = _kernel_stores(db)
    run = PlasticityScanner(afs.conn, store).scan(dry_run=dry_run)
    if _json_out(ctx, run.to_dict()):
        return
    console.print(
        f"scanned {len(run.decisions)}  demoted={list(run.demoted)}  retired={list(run.retired)}"
        + ("  [dim](dry-run)[/dim]" if dry_run else "")
    )
    for d in run.decisions:
        if d.action != "hold":
            console.print(f"  [yellow]{d.action}[/yellow] #{d.skill_id} [{d.verdict}] {d.reason}")


@skills_plasticity.command("lifecycle")
@click.argument("skill_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_plasticity_lifecycle(ctx, skill_id: int, db: str):
    """Show a skill's lifecycle transitions (active/demoted/retired/restored)."""
    from bene.kernel.memory import PlasticityScanner

    afs, store = _kernel_stores(db)
    trail = PlasticityScanner(afs.conn, store).lifecycle(skill_id)
    if _json_out(ctx, trail):
        return
    if not trail:
        console.print(f"[dim]Skill #{skill_id}: no lifecycle transitions (active)[/dim]")
        return
    for t in trail:
        console.print(
            f"{t['decided_at']}  [cyan]{t['status']}[/cyan]  {t['reason']}  ({t['decided_by']})"
        )


@skills_plasticity.command("restore")
@click.argument("skill_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_plasticity_restore(ctx, skill_id: int, db: str):
    """Restore a demoted/retired skill back into search results."""
    from bene.kernel.memory import PlasticityScanner

    afs, store = _kernel_stores(db)
    PlasticityScanner(afs.conn, store).restore(skill_id, decided_by="human")
    result = {"skill_id": skill_id, "status": "restored"}
    if _json_out(ctx, result):
        return
    console.print(f"[green]Skill #{skill_id} restored[/green]")


@cli.group("obsidian")
def obsidian_group():
    """Export a BENE database to an Obsidian-compatible markdown vault."""


@obsidian_group.command("export")
@click.option(
    "--vault",
    required=True,
    type=click.Path(),
    help="Path to the vault directory (created if missing)",
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option(
    "--clean",
    is_flag=True,
    default=False,
    help="Wipe generated directories/files before export (preserves "
    ".obsidian/workspace* and any hand-written notes outside "
    "the owned folders).",
)
@click.pass_context
def obsidian_export(ctx, vault: str, db: str, clean: bool):
    """Render agents, skills, memory, checkpoints, and the shared log as a vault."""
    from bene.obsidian import VaultExporter

    if not Path(db).exists():
        msg = f"Database not found: {db}"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    exporter = VaultExporter(db_path=db, vault_path=vault)
    stats = exporter.export_all(clean=clean)

    result = {
        "vault": str(exporter.vault_path),
        "db": db,
        "agents": stats.agents,
        "skills": stats.skills,
        "memories": stats.memories,
        "checkpoints": stats.checkpoints,
        "log_entries": stats.log_entries,
        "files_written": stats.files_written,
    }
    if _json_out(ctx, result):
        return
    console.print(f"[green]\u2714 Vault exported:[/green] {exporter.vault_path}")
    console.print(
        f"  {stats.agents} agents  \u00b7  {stats.skills} skills  \u00b7  "
        f"{stats.memories} memories  \u00b7  {stats.checkpoints} checkpoints  \u00b7  "
        f"{stats.log_entries} log entries"
    )
    console.print(f"  [dim]{stats.files_written} files written[/dim]")
    console.print(
        "\n  Open the folder in Obsidian: "
        "[cyan]Manage Vaults \u2192 Open folder as vault \u2192 select the path above[/cyan]"
    )


@obsidian_group.command("info")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def obsidian_info(ctx, db: str):
    """Preview what would be exported without writing anything."""
    import sqlite3 as _sqlite3

    if not Path(db).exists():
        msg = f"Database not found: {db}"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    conn = _sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = _sqlite3.Row
    try:
        counts: dict[str, int] = {}
        for table, label in [
            ("agents", "agents"),
            ("agent_skills", "skills"),
            ("memory", "memories"),
            ("checkpoints", "checkpoints"),
            ("shared_log", "log_entries"),
        ]:
            try:
                counts[label] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except _sqlite3.OperationalError:
                counts[label] = 0
    finally:
        conn.close()

    if _json_out(ctx, counts):
        return
    console.print(f"[bold]Export preview for[/bold] {db}")
    for key, n in counts.items():
        console.print(f"  {key:<14} {n}")


# ─────────────────────────────────────────────────────────────────────────
# Temporal — distributed/durable agent execution
# ─────────────────────────────────────────────────────────────────────────


@cli.group("temporal")
def temporal_group():
    """Run BENE agents on a Temporal cluster (durable, horizontally scalable).

    Requires the optional ``[temporal]`` extra::

        pip install 'bene[temporal]'

    Quickstart with docker compose::

        docker compose -f docker/docker-compose.yml up -d
        bene temporal worker --address localhost:7233 \\
            --postgres-dsn YOUR_DSN_HERE
        bene temporal run --address localhost:7233 \\
            --name demo --prompt "say hello"
    """


@temporal_group.command("worker")
@click.option("--address", default="localhost:7233", help="Temporal frontend address")
@click.option("--namespace", default="default", help="Temporal namespace")
@click.option("--queue", default="bene-main", help="Task queue name")
@click.option("--db", default=None, help="SQLite DB path (used when --postgres-dsn is omitted)")
@click.option("--postgres-dsn", default=None, help="Postgres DSN; enables the Postgres backend")
def temporal_worker(address, namespace, queue, db, postgres_dsn):
    """Start a BENE Temporal worker (registers AgentWorkflow + Activities)."""
    try:
        from bene.temporal.worker import main_cli
    except ImportError as exc:
        console.print(
            f"[red]Temporal extras not installed:[/red] {exc}\n"
            "Install with: pip install 'bene[temporal]'"
        )
        sys.exit(1)
    main_cli(
        address=address,
        namespace=namespace,
        task_queue=queue,
        sqlite_db=db,
        postgres_dsn=postgres_dsn,
    )


@temporal_group.command("run")
@click.option("--address", default="localhost:7233", help="Temporal frontend address")
@click.option("--namespace", default="default", help="Temporal namespace")
@click.option("--queue", default="bene-main", help="Task queue name")
@click.option("--name", required=True, help="Agent name")
@click.option("--prompt", default="", help="Initial prompt")
@click.option("--model", default="echo", help="Model alias (handler decides)")
@click.option("--max-steps", default=5, type=int, help="Max workflow steps")
@click.option(
    "--workflow-id",
    default=None,
    help="Override workflow_id (defaults to a fresh ULID; reusing one is idempotent)",
)
@click.pass_context
def temporal_run(ctx, address, namespace, queue, name, prompt, model, max_steps, workflow_id):
    """Start an AgentWorkflow on Temporal and wait for the result."""
    try:
        from temporalio.client import Client

        from bene.temporal.workflow import AgentInput, AgentWorkflow
    except ImportError as exc:
        console.print(
            f"[red]Temporal extras not installed:[/red] {exc}\n"
            "Install with: pip install 'bene[temporal]'"
        )
        sys.exit(1)

    import ulid as _ulid

    agent_id = workflow_id or str(_ulid.new())

    async def _run():
        client = await Client.connect(address, namespace=namespace)
        result = await client.execute_workflow(
            AgentWorkflow.run,
            AgentInput(
                agent_id=agent_id,
                name=name,
                prompt=prompt,
                model=model,
                max_steps=max_steps,
            ),
            id=agent_id,
            task_queue=queue,
        )
        return result

    result = asyncio.run(_run())
    summary = {
        "agent_id": result.agent_id,
        "status": result.status,
        "steps": result.steps,
        "last_output": result.last_output,
    }
    if _json_out(ctx, summary):
        return
    console.print(
        f"[green]Agent {result.agent_id}[/green] {result.status} after {result.steps} steps"
    )
    if result.last_output:
        console.print(f"  last_output: {result.last_output}")


@temporal_group.command("signal")
@click.option("--address", default="localhost:7233", help="Temporal frontend address")
@click.option("--namespace", default="default", help="Temporal namespace")
@click.argument("workflow_id")
@click.argument("signal_name", type=click.Choice(["pause", "resume", "kill"]))
def temporal_signal(address, namespace, workflow_id, signal_name):
    """Send pause/resume/kill to a running AgentWorkflow."""
    try:
        from temporalio.client import Client
    except ImportError:
        console.print("[red]Temporal extras not installed[/red]")
        sys.exit(1)

    async def _send():
        client = await Client.connect(address, namespace=namespace)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(signal_name)

    asyncio.run(_send())
    console.print(f"[green]signal {signal_name}[/green] sent to {workflow_id}")


# ============================================================
# Kernel groups (BENE 2.0): probe / trust / experiments
# ============================================================


def _kernel_stores(db: str):
    """Open a Bene db with v2 tables ensured; returns (afs, store)."""
    from bene.kernel import EngramStore, ensure_v2

    afs = _get_afs(db)
    ensure_v2(afs.conn)
    return afs, EngramStore(afs.conn, afs.blobs)


@cli.group()
def probe():
    """Falsifiable-eval probes (pre-registered, hash-locked kill gates)."""


@probe.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option(
    "--check-admissible",
    is_flag=True,
    default=False,
    help="Exit non-zero if any registered probe is inadmissible (CI guard against can't-fail probes)",
)
@click.pass_context
def probe_ls(ctx, db: str, check_admissible: bool):
    """List registered probes.

    With ``--check-admissible`` the command is a CI guard: it exits non-zero if
    any registered probe is ``inadmissible`` (a gate its baseline already passes
    — it can never catch a regression), and zero when every probe is admissible.
    """
    afs, _ = _kernel_stores(db)
    rows = afs.conn.execute(
        "SELECT name, status, lock_sha256, subject_ref, created_at"
        " FROM probe_registry ORDER BY created_at DESC"
    ).fetchall()
    data = [
        {
            "name": r[0],
            "status": r[1],
            "lock_sha256": r[2][:16] + "...",
            "subject_ref": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]
    inadmissible = [p["name"] for p in data if p["status"] == "inadmissible"]

    if check_admissible:
        result = {"ok": not inadmissible, "inadmissible": inadmissible, "total": len(data)}
        if not _json_out(ctx, result):
            if inadmissible:
                console.print(
                    f"[red]{len(inadmissible)} inadmissible probe(s):[/red] {', '.join(inadmissible)}"
                )
                console.print(
                    "[dim]An inadmissible probe's baseline passes every gate — it can never catch"
                    " a regression. Re-author buggy-incumbent-must-fail (see docs/probe-authoring.md).[/dim]"
                )
            else:
                console.print(f"[green]all {len(data)} probe(s) admissible[/green]")
        if inadmissible:
            sys.exit(1)
        return

    if _json_out(ctx, data):
        return
    if not data:
        console.print("[dim]No probes registered. Register one via bene.kernel.eval.Probe.[/dim]")
        return
    for p in data:
        colour = "green" if p["status"] == "admissible" else "red"
        console.print(
            f"[{colour}]{p['status']:>13}[/{colour}]  {p['name']}  lock={p['lock_sha256']}"
        )


@probe.command("show")
@click.argument("name")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def probe_show(ctx, name: str, db: str):
    """Show a probe's locked gate spec and status."""
    afs, _ = _kernel_stores(db)
    row = afs.conn.execute(
        "SELECT probe_id, name, gate_spec, lock_sha256, status, subject_ref, created_at"
        " FROM probe_registry WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        if not _json_err(ctx, f"probe not found: {name}"):
            console.print(f"[red]probe not found:[/red] {name}")
        sys.exit(1)
    data = {
        "probe_id": row[0],
        "name": row[1],
        "gates": json.loads(row[2]),
        "lock_sha256": row[3],
        "status": row[4],
        "subject_ref": row[5],
        "created_at": row[6],
    }
    if _json_out(ctx, data):
        return
    console.print_json(json.dumps(data, default=str))


@probe.command("run")
@click.argument("name")
@click.option(
    "--subject",
    "subject_path",
    required=True,
    help="Path to a JSON file of the subject's metrics: {metric: number, ...}",
)
@click.option(
    "--baseline",
    "baseline_path",
    default=None,
    help="Path to a JSON file of baseline metrics (defaults to {} — required for relative gates)",
)
@click.option("--subject-ref", default=None, help="Engram id the verdict verifies/refutes")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def probe_run(ctx, name, subject_path, baseline_path, subject_ref, db):
    """Run a registered probe against subject/baseline metrics and emit the verdict.

    Evaluates the probe's hash-locked gates (verifying the lock) against the
    metrics in ``--subject`` (and ``--baseline``). Prints the ACCEPT/REJECT/VOID
    verdict and EXITS NON-ZERO on REJECT or VOID so CI can gate on it. The metrics
    are the ``{metric: number}`` dicts a probe's ``evaluate_fn`` would produce —
    supplying them as files keeps the CLI decoupled from in-process callables.
    """
    import hashlib

    from bene.kernel.eval.gates import evaluate_gate
    from bene.kernel.eval.verdict import ACCEPT, REJECT, VOID, Verdict, persist_verdict

    afs, store = _kernel_stores(db)
    row = afs.conn.execute(
        "SELECT probe_id, gate_spec, lock_sha256, status, subject_ref"
        " FROM probe_registry WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        if not _json_err(ctx, f"probe not found: {name}"):
            console.print(f"[red]probe not found:[/red] {name}")
        sys.exit(1)
    probe_id, stored_spec, stored_lock, status, registered_ref = row

    # Honour the hash-lock: the stored spec must hash to its recorded lock.
    if hashlib.sha256(stored_spec.encode()).hexdigest() != stored_lock:
        if not _json_err(ctx, f"probe {name}: stored gate spec does not match its lock"):
            console.print(f"[red]LockTamperError:[/red] probe {name} spec/lock mismatch")
        sys.exit(2)

    def _load_metrics(path, label):
        if path is None:
            return {}
        try:
            with open(path) as fh:
                m = json.load(fh)
            if not isinstance(m, dict):
                raise ValueError("metrics file must be a JSON object")
            return m
        except Exception as e:  # noqa: BLE001 — surface a clean CLI error
            if not _json_err(ctx, f"{label} metrics unreadable ({path}): {e}"):
                console.print(f"[red]{label} metrics unreadable:[/red] {e}")
            sys.exit(2)

    gates = json.loads(stored_spec)
    ref = subject_ref or registered_ref

    if status == "inadmissible":
        verdict = persist_verdict(
            Verdict(VOID, name, [], reason="probe is inadmissible"),
            store=store,
            conn=afs.conn,
            probe_id=probe_id,
            subject_ref=ref,
        )
    else:
        subject_metrics = _load_metrics(subject_path, "subject")
        baseline_metrics = _load_metrics(baseline_path, "baseline")
        results = [evaluate_gate(g, subject_metrics, baseline_metrics) for g in gates]
        status_out = REJECT if any(r["killed"] for r in results) else ACCEPT
        verdict = persist_verdict(
            Verdict(status_out, name, results),
            store=store,
            conn=afs.conn,
            probe_id=probe_id,
            subject_ref=ref,
        )

    out = {
        "status": verdict.status,
        "probe": verdict.probe_name,
        "gate_results": verdict.gate_results,
        "reason": verdict.reason,
        "engram_id": verdict.engram_id,
        "killed_gates": verdict.killed_gates,
    }
    if not _json_out(ctx, out):
        colour = "green" if verdict.status == ACCEPT else "red"
        console.print(f"[{colour}]{verdict.status}[/{colour}]  {name}")
        if verdict.killed_gates:
            console.print(f"  killed: {', '.join(verdict.killed_gates)}")
        if verdict.reason:
            console.print(f"  reason: {verdict.reason}")
    # CI contract: non-zero exit on anything but ACCEPT.
    if verdict.status != ACCEPT:
        sys.exit(1)


@cli.command("trust")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def trust_cmd(ctx, agent_id: str, db: str):
    """Per-agent computed trust summary (4 signals + composite)."""
    from bene.kernel.trust import TrustLedger

    afs, store = _kernel_stores(db)
    ledger = TrustLedger(afs.conn, store)
    data = ledger.summary(agent_id)
    if _json_out(ctx, data):
        return
    console.print(f"[bold]Trust — {agent_id}[/bold]  composite={data['composite']}")
    for name, sig in data["signals"].items():
        console.print(f"  {name:>24}: {sig['value']:<7} (w={sig['weight']})  {sig['note']}")
    if data["denials"]:
        console.print(f"  [yellow]{data['denials']} autonomy denial(s) on record[/yellow]")


@cli.group()
def experiments():
    """Experiments journal (probe / evolution / consolidation runs)."""


@experiments.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--kind", default=None, help="Filter by kind (probe/evolution/consolidation/sweep)")
@click.pass_context
def experiments_ls(ctx, db: str, kind: str | None):
    """List logged experiment runs."""
    afs, _ = _kernel_stores(db)
    sql = "SELECT run_id, kind, summary, created_at FROM experiment_runs"
    params: list = []
    if kind:
        sql += " WHERE kind = ?"
        params.append(kind)
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = afs.conn.execute(sql, params).fetchall()
    data = [{"run_id": r[0], "kind": r[1], "summary": r[2], "created_at": r[3]} for r in rows]
    if _json_out(ctx, data):
        return
    if not data:
        console.print("[dim]No experiment runs logged yet.[/dim]")
        return
    for e in data:
        console.print(f"{e['created_at']}  [cyan]{e['kind']:>13}[/cyan]  {e['summary']}")


@experiments.command("show")
@click.argument("run_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def experiments_show(ctx, run_id: str, db: str):
    """Show one experiment run incl. its verdict engram."""
    afs, store = _kernel_stores(db)
    row = afs.conn.execute(
        "SELECT run_id, kind, probe_id, verdict_engram, summary, metrics, created_at"
        " FROM experiment_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        if not _json_err(ctx, f"run not found: {run_id}"):
            console.print(f"[red]run not found:[/red] {run_id}")
        sys.exit(1)
    data = {
        "run_id": row[0],
        "kind": row[1],
        "probe_id": row[2],
        "verdict_engram": row[3],
        "summary": row[4],
        "metrics": json.loads(row[5]),
        "created_at": row[6],
    }
    if row[3]:
        data["verdict_payload"] = store.payload(row[3]).decode(errors="replace")
    if _json_out(ctx, data):
        return
    console.print_json(json.dumps(data, default=str))


# ---- scheduled memory consolidation (cron-spawnable) ----

# Built-in policies so `bene consolidate run --policy nightly` works with no
# config; bene.yaml kernel.consolidation.policies overlays/overrides these.
_BUILTIN_CONSOLIDATION_POLICIES = {
    "nightly": {
        "to_level": "episode",
        "min_turns": 4,
        "batch_size": 8,
        "max_batches": 1,
        "interval_hours": 24.0,
    },
    "weekly_semantic": {
        "to_level": "semantic",
        "min_turns": 6,
        "batch_size": 12,
        "max_batches": 1,
        "interval_hours": 168.0,
    },
}


def _resolve_consolidation_policy(name: str, config_path: str, agent: str | None):
    """Built-ins overlaid by kernel.consolidation config. Raises ValueError on
    unknown policy name or invalid config (caller maps that to exit 1)."""
    from dataclasses import replace

    from bene.config import consolidation_policies_from_config_file
    from bene.kernel.memory import ConsolidationPolicy

    policies = {
        n: ConsolidationPolicy.from_dict(spec)
        for n, spec in _BUILTIN_CONSOLIDATION_POLICIES.items()
    }
    if os.path.exists(config_path):
        policies.update(consolidation_policies_from_config_file(config_path))
    if name not in policies:
        raise ValueError(f"unknown policy {name!r} (known: {', '.join(sorted(policies))})")
    policy = policies[name]
    return replace(policy, agent_id=agent) if agent else policy


def _consolidate_exit_code(plan) -> int:
    """Cron contract: 0 = ran or healthy interval-skip, 2 = insufficient-turns."""
    if plan.due:
        return 0
    if plan.reason == "insufficient-turns":
        return 2
    return 0


@cli.group("consolidate")
def consolidate():
    """Scheduled memory consolidation (cron-spawnable; turn → episode/semantic)."""


@consolidate.command("plan")
@click.option("--policy", "policy_name", default="nightly", help="Policy name (built-in or config)")
@click.option("--agent", default=None, help="Restrict to one agent_id")
@click.option("--force", is_flag=True, default=False, help="Ignore the interval gate")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config", default=DEFAULT_CONFIG, help="bene.yaml path")
@click.pass_context
def consolidate_plan(ctx, policy_name, agent, force, db, config):
    """Show what a consolidation run would do (no mutation)."""
    from bene.kernel.memory import ScheduledConsolidator

    try:
        policy = _resolve_consolidation_policy(policy_name, config, agent)
    except (ValueError, TypeError) as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
        sys.exit(1)
    _, store = _kernel_stores(db)
    plan = ScheduledConsolidator(store).plan(policy, force=force)
    manifest = plan.replay_manifest()
    if not _json_out(ctx, manifest):
        console.print(f"due={plan.due} reason={plan.reason} batches={len(plan.batches)}")
    sys.exit(_consolidate_exit_code(plan))


@consolidate.command("run")
@click.option("--policy", "policy_name", default="nightly", help="Policy name (built-in or config)")
@click.option("--agent", default=None, help="Restrict to one agent_id")
@click.option("--force", is_flag=True, default=False, help="Ignore the interval gate")
@click.option("--dry-run", is_flag=True, default=False, help="Plan + report, do not mutate")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config", default=DEFAULT_CONFIG, help="bene.yaml path")
@click.pass_context
def consolidate_run(ctx, policy_name, agent, force, dry_run, db, config):
    """Run a due consolidation. Exit 0 ran/interval-skip · 1 error · 2 insufficient-turns."""
    from bene.kernel.memory import ScheduledConsolidator

    try:
        policy = _resolve_consolidation_policy(policy_name, config, agent)
    except (ValueError, TypeError) as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
        sys.exit(1)
    _, store = _kernel_stores(db)
    try:
        run = ScheduledConsolidator(store).run(policy, force=force, dry_run=dry_run)
    except Exception as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
        sys.exit(1)
    if not _json_out(ctx, run.to_dict()):
        console.print(
            f"due={run.plan.due} reason={run.plan.reason} "
            f"created={len(run.created_engram_ids)} run_id={run.run_id}"
        )
    sys.exit(_consolidate_exit_code(run.plan))


@consolidate.command("ls")
@click.option("--limit", default=20, help="Max rows")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def consolidate_ls(ctx, limit, db):
    """List recent consolidation runs."""
    afs, _ = _kernel_stores(db)
    rows = afs.conn.execute(
        "SELECT run_id, summary, created_at FROM experiment_runs"
        " WHERE kind='consolidation' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    data = [{"run_id": r[0], "summary": r[1], "created_at": r[2]} for r in rows]
    if _json_out(ctx, data):
        return
    if not data:
        console.print("[dim]No consolidation runs.[/dim]")
        return
    for e in data:
        console.print(f"{e['created_at']}  [cyan]{e['run_id']}[/cyan]  {e['summary']}")


@consolidate.command("show")
@click.argument("run_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def consolidate_show(ctx, run_id, db):
    """Show one consolidation run's replay manifest."""
    afs, _ = _kernel_stores(db)
    row = afs.conn.execute(
        "SELECT run_id, summary, metrics, created_at FROM experiment_runs"
        " WHERE run_id=? AND kind='consolidation'",
        (run_id,),
    ).fetchone()
    if row is None:
        if not _json_err(ctx, f"consolidation run not found: {run_id}"):
            console.print(f"[red]not found:[/red] {run_id}")
        sys.exit(1)
    data = {
        "run_id": row[0],
        "summary": row[1],
        "metrics": json.loads(row[2]),
        "created_at": row[3],
    }
    if _json_out(ctx, data):
        return
    console.print_json(json.dumps(data, default=str))


# ---- entropy-routed retrieval (MemGAS, opt-in) ----


@cli.command("retrieve")
@click.argument("query")
@click.option("--agent", default=None, help="Attribute the query engram to this agent_id")
@click.option("--k", default=8, help="Max hits to return")
@click.option("--tiers", default=None, help="MemGAS tiers, comma ints e.g. 0,2,3,4")
@click.option(
    "--memgas/--adaptive", "use_memgas", default=None, help="Force router (default: config)"
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config", default=DEFAULT_CONFIG, help="bene.yaml path")
@click.pass_context
def retrieve(ctx, query, agent, k, tiers, use_memgas, db, config):
    """Retrieve engrams; MemGAS entropy router when enabled, else adaptive."""
    from bene.config import load_config, memgas_config_from_config
    from bene.kernel.memory import AdaptiveRetriever, MemGASResult, MemGASRouter

    _, store = _kernel_stores(db)
    cfg: dict = {}
    if os.path.exists(config):
        try:
            cfg = memgas_config_from_config(load_config(config))
        except Exception:
            cfg = {}
    want_memgas = cfg.get("enabled", False) if use_memgas is None else use_memgas
    if want_memgas:
        kwargs = {kk: vv for kk, vv in cfg.items() if kk != "enabled"}
        if tiers:
            kwargs["tiers"] = tuple(int(t) for t in tiers.split(","))
        result = MemGASRouter(store, **kwargs).query(agent, query, k=k)
    else:
        result = AdaptiveRetriever(store).query(agent, query, k=k)

    data = {
        "query": result.query,
        "router": "memgas" if isinstance(result, MemGASResult) else "adaptive",
        "path": result.path,
        "familiarity": round(result.familiarity, 4),
        "hits": [{"engram_id": e.engram_id, "tier": e.tier, "title": e.title} for e in result.hits],
    }
    if isinstance(result, MemGASResult):
        data["routed_tiers"] = result.routed_tiers
        data["tier_probes"] = [
            {
                "tier": p.tier,
                "entropy": round(p.entropy, 4),
                "weight": round(p.weight, 4),
                "hits": len(p.hits),
            }
            for p in result.tier_probes
        ]
    if _json_out(ctx, data):
        return
    console.print(
        f"[cyan]{data['router']}[/cyan]/{result.path}  fam={data['familiarity']}  hits={len(result.hits)}"
    )
    if isinstance(result, MemGASResult):
        console.print(f"  routed_tiers={result.routed_tiers}")
    for e in result.hits[:10]:
        console.print(f"  [dim]t{e.tier}[/dim] {e.title}")


# ---- signed deterministic replay (consolidation v1) ----

DEFAULT_REPLAY_KEY = "~/.config/bene/replay_ed25519.key"


def _resolve_sign_key(key_file: str | None):
    """Load the signing key, generating + persisting one (0600, outside the
    repo) at the default path on first use so ``--sign`` is frictionless."""
    from bene.kernel.replay import keys as _keys

    path = Path(key_file).expanduser() if key_file else Path(DEFAULT_REPLAY_KEY).expanduser()
    if path.exists():
        return _keys.load_private_key(path)
    key = _keys.generate_private_key()
    _keys.write_key_file(key, path)
    click.echo(f"generated signing key: {path}", err=True)
    return key


@cli.group("replay")
def replay():
    """Signed deterministic replay of recorded runs (consolidation v1)."""


@replay.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--kind", default="consolidation", help="Run kind to list")
@click.pass_context
def replay_ls(ctx, db: str, kind: str):
    """List exportable runs (= experiment_runs of this kind)."""
    from bene.kernel.replay import ReplayExporter

    _, store = _kernel_stores(db)
    runs = ReplayExporter(store).list_runs(kind=kind)
    if _json_out(ctx, runs):
        return
    if not runs:
        console.print("[dim]No exportable runs.[/dim]")
        return
    for r in runs:
        console.print(f"{r['created_at']}  [cyan]{r['run_id']}[/cyan]  {r['summary']}")


@replay.command("export")
@click.argument("run_id")
@click.option("--out", default=None, help="Write envelope to this path (default: stdout)")
@click.option("--sign/--no-sign", default=False, help="ed25519-sign the envelope")
@click.option(
    "--key-file", default=None, help="Signing key (default: ~/.config/bene/replay_ed25519.key)"
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def replay_export(ctx, run_id: str, out: str | None, sign: bool, key_file: str | None, db: str):
    """Export a recorded run into a .bene-replay envelope."""
    from bene.kernel.replay import ReplayExporter, UnknownRun

    _, store = _kernel_stores(db)
    sign_key = _resolve_sign_key(key_file) if sign else None
    try:
        env = ReplayExporter(store).export(run_id, sign_key=sign_key)
    except (UnknownRun, ValueError) as e:
        msg = f"cannot export {run_id}: {e}"
        if not _json_err(ctx, msg):
            console.print(f"[red]{msg}[/red]")
        sys.exit(1)
    text = env.to_json()
    if out:
        Path(out).expanduser().write_text(text)
        data = {"out": out, "run_id": run_id, "signed": bool(sign_key), "digest": env.digest()}
        if _json_out(ctx, data):
            return
        console.print(f"[green]wrote[/green] {out}  sha256:{env.digest()[:16]}…")
    else:
        click.echo(text)


@replay.command("verify")
@click.argument("envelope_file")
@click.option("--into", default=None, help="Sandbox db path (default: in-memory)")
@click.option("--trusted-keys", default=None, help="JSON file: list of base64 public keys")
@click.pass_context
def replay_verify(ctx, envelope_file: str, into: str | None, trusted_keys: str | None):
    """Re-derive an envelope in a sandbox; exits non-zero on mismatch."""
    from bene.kernel.replay import ReplayEnvelope, ReplayVerifier

    env = ReplayEnvelope.from_json(Path(envelope_file).expanduser().read_text())
    tk = set(json.loads(Path(trusted_keys).expanduser().read_text())) if trusted_keys else None
    result = ReplayVerifier(trusted_keys=tk).verify(env, into_db=into)
    data = result.to_dict()
    if ctx.obj.get("json"):
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        status = "[green]OK[/green]" if result.ok else "[red]MISMATCH[/red]"
        console.print(f"{status}  signature={result.signature_state}")
        if result.reasons:
            console.print(f"  reasons: {', '.join(result.reasons)}")
    if not result.ok:
        sys.exit(1)


@replay.command("cite")
@click.argument("run_id")
@click.option("--style", default="bibtex", type=click.Choice(["bibtex", "json"]))
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def replay_cite(ctx, run_id: str, style: str, db: str):
    """Print a citation referencing a run's replay artifact by content digest."""
    from bene.kernel.replay import ReplayExporter, UnknownRun

    _, store = _kernel_stores(db)
    try:
        env = ReplayExporter(store).export(run_id)
    except (UnknownRun, ValueError) as e:
        msg = f"cannot cite {run_id}: {e}"
        if not _json_err(ctx, msg):
            console.print(f"[red]{msg}[/red]")
        sys.exit(1)
    click.echo(env.cite_as(style=style))


@replay.command("keygen")
@click.option("--key-file", default=DEFAULT_REPLAY_KEY, help="Where to write the private key")
@click.pass_context
def replay_keygen(ctx, key_file: str):
    """Generate an ed25519 signing key (0600, outside the repo)."""
    from bene.kernel.replay import keys as _keys

    key = _keys.generate_private_key()
    path = _keys.write_key_file(key, key_file)
    data = {"key_file": str(path), "public_key": _keys.public_key_b64(key)}
    if _json_out(ctx, data):
        return
    console.print(f"[green]wrote[/green] {path} (0600)\npublic_key: {data['public_key']}")


# ---- pluggable agent-loop observability ----


def _observability_config(config_path: str) -> dict:
    """Extract ``kernel.observability`` from bene.yaml; {} if absent/unreadable."""
    try:
        cfg = load_config(config_path)
    except Exception:
        return {}
    kernel = cfg.get("kernel") if isinstance(cfg, dict) else None
    obs = kernel.get("observability") if isinstance(kernel, dict) else None
    return obs if isinstance(obs, dict) else {}


@cli.group("observe")
def observe():
    """Pluggable agent-loop observability (langfuse-first; OTel/Phoenix pluggable)."""


@observe.command("status")
@click.option("--config", default=DEFAULT_CONFIG, help="bene.yaml path")
@click.pass_context
def observe_status(ctx, config: str):
    """Report which observability backend the runner would select."""
    import importlib.util

    import bene.observe.langfuse  # noqa: F401 — import to self-register the adapter
    from bene.observe import available_providers, resolve_provider

    # The langfuse adapter self-registers as "available" on import even when the
    # SDK is absent (the SDK import is deferred), so probe it explicitly here.
    langfuse_sdk_installed = importlib.util.find_spec("langfuse") is not None
    obs_cfg = _observability_config(config)
    host = os.environ.get("LANGFUSE_HOST") or None
    data = {
        "selected_provider": resolve_provider(obs_cfg),
        "available_providers": available_providers(),
        "langfuse_host": host,
        "langfuse_sdk_installed": langfuse_sdk_installed,
        "config": obs_cfg,
    }
    if _json_out(ctx, data):
        return
    console.print(f"observability backend: [cyan]{data['selected_provider']}[/cyan]")
    console.print(f"  available providers: {', '.join(data['available_providers'])}")
    console.print(f"  LANGFUSE_HOST: {host or '[dim]unset[/dim]'}")
    if (
        data["selected_provider"] == "langfuse" or "langfuse" in data["available_providers"]
    ) and not langfuse_sdk_installed:
        console.print(
            "  [yellow]langfuse selected but its SDK is not installed[/yellow] — "
            'install: pip install "bene[langfuse]"'
        )
    if data["selected_provider"] == "null":
        console.print(
            "  [dim]traces disabled — set LANGFUSE_HOST or kernel.observability.provider[/dim]"
        )


# ---- continual harness (probe-gated in-episode genome swaps) ----


@cli.group("evolve")
def evolve_group():
    """Evolution surfaces (continual in-episode genome mutation)."""


@evolve_group.group("continual")
def evolve_continual():
    """Continual Harness — probe-gated in-episode genome swaps."""


@evolve_continual.command("status")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def evolve_continual_status(ctx, agent_id: str, db: str):
    """Show an agent's in-episode swap history + active genome engram."""
    afs, _ = _kernel_stores(db)
    cols = [
        "swap_id",
        "episode_id",
        "turn",
        "trigger_reason",
        "component",
        "child_genome_engram_id",
        "verdict_engram_id",
        "swap_at",
    ]
    try:
        rows = afs.conn.execute(
            "SELECT swap_id, episode_id, turn, trigger_reason, component,"
            " child_genome_engram_id, verdict_engram_id, swap_at FROM continual_swaps"
            " WHERE agent_id=? ORDER BY swap_at ASC, swap_id ASC",
            (agent_id,),
        ).fetchall()
    except Exception:
        rows = []  # table not provisioned (no continual swaps ever)
    swaps = [dict(zip(cols, r)) for r in rows]
    data = {
        "agent_id": agent_id,
        "active_genome_engram_id": swaps[-1]["child_genome_engram_id"] if swaps else None,
        "swaps": swaps,
    }
    if _json_out(ctx, data):
        return
    if not swaps:
        console.print(f"[dim]No continual swaps for {agent_id}[/dim]")
        return
    console.print(
        f"[bold]Continual swaps[/bold] for {agent_id}  active={data['active_genome_engram_id']}"
    )
    for s in swaps:
        console.print(
            f"{s['swap_at']}  [cyan]{s['component']}[/cyan]  trigger={s['trigger_reason']}"
            f"  child={s['child_genome_engram_id']}"
        )


# ---- spec-driven development: propose → accept (gated) → spec ----


@cli.group("spec")
def spec_group():
    """SDD gating: propose → accept (behind an ACCEPT verdict) → spec."""


@spec_group.command("propose")
@click.argument("title")
@click.option("--body", default=None, help="Proposal body text")
@click.option("--body-file", default=None, help="Read the body from a file")
@click.option("--agent", default=None, help="Attribute to this agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def spec_propose(ctx, title, body, body_file, agent, db):
    """Create a proposal engram (status: proposed)."""
    from bene.kernel.spec import SpecWorkflow

    afs, store = _kernel_stores(db)
    text = body if body is not None else (Path(body_file).read_text() if body_file else "")
    pid = SpecWorkflow(store, afs.conn).propose(title, text, agent_id=agent)
    afs.conn.commit()
    data = {"proposal_id": pid, "title": title, "status": "proposed"}
    if _json_out(ctx, data):
        return
    console.print(f"[green]proposed[/green] {pid}  {title}")


@spec_group.command("accept")
@click.argument("proposal_id")
@click.option("--verdict", default=None, help="ACCEPT eval engram id (probe-gated path)")
@click.option("--human", default=None, help="Accept as the named human reviewer (human-gated path)")
@click.option("--rationale", default="", help="Why it was accepted")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def spec_accept(ctx, proposal_id, verdict, human, rationale, db):
    """Promote a proposal to a spec — only behind an ACCEPT verdict."""
    from bene.kernel.spec import SpecGateBlocked, SpecWorkflow

    afs, store = _kernel_stores(db)
    decided_by = f"human:{human}" if human else ""
    try:
        spec_id = SpecWorkflow(store, afs.conn).accept(
            proposal_id, verdict_engram_id=verdict, decided_by=decided_by, rationale=rationale
        )
    except (SpecGateBlocked, KeyError) as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
        sys.exit(1)
    data = {"proposal_id": proposal_id, "spec_id": spec_id, "status": "accepted"}
    if _json_out(ctx, data):
        return
    console.print(f"[green]accepted[/green] {proposal_id} → spec {spec_id}")


@spec_group.command("reject")
@click.argument("proposal_id")
@click.option("--human", default="human", help="Rejecting reviewer")
@click.option("--rationale", default="", help="Why it was rejected")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def spec_reject(ctx, proposal_id, human, rationale, db):
    """Reject a proposal (append-only)."""
    from bene.kernel.spec import SpecWorkflow

    afs, store = _kernel_stores(db)
    rid = SpecWorkflow(store, afs.conn).reject(proposal_id, decided_by=human, rationale=rationale)
    data = {"proposal_id": proposal_id, "rejection_engram": rid, "status": "rejected"}
    if _json_out(ctx, data):
        return
    console.print(f"[yellow]rejected[/yellow] {proposal_id}")


@spec_group.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def spec_ls(ctx, db):
    """List proposals and their gating status."""
    from bene.kernel.spec import SpecWorkflow

    afs, store = _kernel_stores(db)
    views = [v.to_dict() for v in SpecWorkflow(store, afs.conn).ls()]
    if _json_out(ctx, views):
        return
    if not views:
        console.print("[dim]No proposals.[/dim]")
        return
    for v in views:
        color = {"accepted": "green", "rejected": "yellow", "proposed": "cyan"}[v["status"]]
        console.print(f"[{color}]{v['status']:>9}[/{color}]  {v['proposal_id']}  {v['title']}")


# ---- autonomy ladder (config defaults + grants) ----

_AUTONOMY_DOMAINS = ("*", "evolve", "memory", "skills", "eval")


@cli.group("autonomy")
def autonomy_group():
    """Autonomy ladder: config defaults + per-domain grants (L0–L4)."""


@autonomy_group.command("show")
@click.argument("agent_id")
@click.option(
    "--config", default=DEFAULT_CONFIG, help="bene.yaml path (for kernel.autonomy defaults)"
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def autonomy_show(ctx, agent_id, config, db):
    """Show an agent's effective autonomy level per domain (config-floored)."""
    from bene.config import autonomy_config_from_config, load_config
    from bene.kernel.harness import AutonomyPolicy

    afs, _ = _kernel_stores(db)
    default_level = 0
    if os.path.exists(config):
        try:
            default_level = int(
                autonomy_config_from_config(load_config(config)).get("default_level", 0)
            )
        except Exception:
            default_level = 0
    policy = AutonomyPolicy(afs.conn, default_level=default_level)
    levels = {d: policy.level_for(agent_id, domain=d) for d in _AUTONOMY_DOMAINS}
    data = {"agent_id": agent_id, "default_level": default_level, "levels": levels}
    if _json_out(ctx, data):
        return
    console.print(f"[bold]autonomy[/bold] {agent_id}  default_level=L{default_level}")
    for d, lvl in levels.items():
        console.print(f"  {d:>8}: [cyan]L{lvl}[/cyan]")


@autonomy_group.command("grant")
@click.argument("agent_id")
@click.argument("level", type=int)
@click.option("--domain", default="*", help="Domain to grant (default: all)")
@click.option("--by", "granted_by", required=True, help="Granter, e.g. human:eddie")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def autonomy_grant(ctx, agent_id, level, domain, granted_by, db):
    """Grant an autonomy level (L4 requires --by human:<name>)."""
    from bene.kernel.harness import AutonomyPolicy

    afs, _ = _kernel_stores(db)
    try:
        AutonomyPolicy(afs.conn).grant(agent_id, level, domain=domain, granted_by=granted_by)
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
        sys.exit(1)
    data = {"agent_id": agent_id, "domain": domain, "level": level, "granted_by": granted_by}
    if _json_out(ctx, data):
        return
    console.print(f"[green]granted[/green] {agent_id} L{level} on {domain}")


@autonomy_group.command("auto-promote")
@click.argument("agent_id")
@click.option("--domain", default="*", help="Domain to promote within")
@click.option("--by", "granted_by", default="trust:auto", help="Granter label for the audit trail")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def autonomy_auto_promote(ctx, agent_id, domain, granted_by, db):
    """Auto-promote an agent to the highest trust-ELIGIBLE level (L0–L3; L4 stays
    human-only). Reads the computed trust composite + probe ACCEPT history."""
    from bene.kernel.harness import AutonomyPolicy
    from bene.kernel.trust import TrustLedger

    afs, store = _kernel_stores(db)
    ledger = TrustLedger(afs.conn, store)
    policy = AutonomyPolicy(afs.conn, store)
    promoted = policy.auto_promote(agent_id, ledger, domain=domain, granted_by=granted_by)
    level = policy.level_for(agent_id, domain=domain)
    data = {"agent_id": agent_id, "domain": domain, "promoted_to": promoted, "level": level}
    if _json_out(ctx, data):
        return
    if promoted is None:
        console.print(
            f"[dim]no promotion[/dim] {agent_id} already at/above eligible level (L{level})"
        )
    else:
        console.print(
            f"[green]auto-promoted[/green] {agent_id} → L{promoted} on {domain} (trust-eligible)"
        )


# ---- failure intelligence (localize the decisive step) ----


@cli.group("failure")
def failure_group():
    """Failure intelligence — localize the earliest decisive step in a failed run."""


@failure_group.command("localize")
@click.argument("agent_id")
@click.option(
    "--persist", is_flag=True, default=False, help="Record the localization as an episodic engram"
)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def failure_localize(ctx, agent_id, persist, db):
    """Localize the earliest decisive failure step in AGENT_ID's trace timeline.

    Reads the agent's trace/episodic engrams (every run_agent turn lands as one),
    classifies them into a timeline, and blames the earliest decisive error
    (heuristic-first). `--persist` records the verdict as a tier-1 episodic engram.
    """
    from bene.kernel.evolve import localize_steps, persist_localization, steps_from_engrams

    afs, store = _kernel_stores(db)
    ids = [
        r[0]
        for r in afs.conn.execute(
            "SELECT engram_id FROM engrams WHERE agent_id = ? AND kind IN ('trace', 'episodic')"
            " ORDER BY created_at",
            (agent_id,),
        ).fetchall()
    ]
    loc = localize_steps(steps_from_engrams(store, ids))
    if loc is None:
        data = {"agent_id": agent_id, "localized": False, "steps": len(ids)}
        if _json_out(ctx, data):
            return
        console.print(
            f"[dim]no decisive failure[/dim] for {agent_id} ({len(ids)} steps, no error step)"
        )
        return
    persisted = None
    if persist:
        persisted = persist_localization(
            store, loc, provenance={"system": "bene.cli.failure"}, agent_id=agent_id
        )
    data = {
        "agent_id": agent_id,
        "localized": True,
        "index": loc.index,
        "label": loc.step.label,
        "rationale": loc.rationale,
        "method": loc.method,
        "confidence": round(loc.confidence, 4),
        "ref": loc.step.ref,
        "persisted_engram": persisted,
    }
    if _json_out(ctx, data):
        return
    console.print(
        f"[bold]failure localized[/bold] {agent_id}  [dim]({loc.method}, conf={loc.confidence:.2f})[/dim]"
    )
    console.print(f"  step #{loc.index}: [red]{loc.step.label}[/red]")
    console.print(f"  why: {loc.rationale}")
    if persisted:
        console.print(f"  [green]recorded[/green] episodic engram {persisted}")


# ---- A2A (Agent2Agent) endpoint ----


@cli.group("a2a")
def a2a_group():
    """A2A (Agent2Agent) endpoint — durable cross-agent comms, seated on SharedLog."""


def _a2a_import(ctx):
    try:
        import bene.a2a as mod

        return mod
    except ModuleNotFoundError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
        sys.exit(1)


@a2a_group.command("card")
@click.option("--url", default=None, help="Public endpoint URL stamped into the card")
@click.pass_context
def a2a_card(ctx, url):
    """Print bene's A2A Agent Card (the /.well-known/agent-card.json document)."""
    mod = _a2a_import(ctx)
    card = mod.build_bene_agent_card(url or mod.card.DEFAULT_URL)
    data = card.model_dump(mode="json", by_alias=True, exclude_none=True)
    if _json_out(ctx, data):
        return
    console.print_json(data=data)


@a2a_group.command("serve")
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8710, help="Bind port")
@click.option("--url", default=None, help="Public URL for the card (default http://host:port/)")
@click.option("--db", default=DEFAULT_DB, help="Database file path (the SharedLog store)")
@click.pass_context
def a2a_serve(ctx, host, port, url, db):
    """Stand up the bene A2A endpoint (blocking)."""
    mod = _a2a_import(ctx)
    public = url or f"http://{host}:{port}/"
    console.print(
        f"[bold]bene a2a[/bold] serving on http://{host}:{port}  card={public}.well-known/agent-card.json"
    )
    mod.serve(db, host=host, port=port, url=public)


@cli.command("senses")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--md", "as_md", is_flag=True, default=False, help="Markdown output")
@click.pass_context
def senses_cmd(ctx, db: str, as_md: bool):
    """Agent senses — discoverability manifest generated from the live db."""
    from bene.kernel.harness import SensesManifest

    afs, _ = _kernel_stores(db)
    out = SensesManifest.generate(afs, fmt="md" if as_md else "json")
    if as_md:
        console.print(out)
        return
    if ctx.obj.get("json"):
        click.echo(out)
    else:
        console.print_json(out)


@cli.command("sweep")
@click.argument("target")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def sweep_cmd(ctx, target: str, db: str):
    """Debt sweeper — scan an agent's VFS (agent_id) or a filesystem path."""
    import os as _os

    from bene.kernel.harness import DebtSweeper

    afs, store = _kernel_stores(db)
    sweeper = DebtSweeper(store)
    if _os.path.exists(target):
        paths = []
        if _os.path.isdir(target):
            for root, _dirs, files in _os.walk(target):
                paths += [
                    _os.path.join(root, f)
                    for f in files
                    if f.endswith((".py", ".md", ".js", ".ts"))
                ]
        else:
            paths = [target]
        report = sweeper.scan_paths(paths)
    else:
        report = sweeper.scan_agent_vfs(afs, target)
    data = {
        "files_scanned": report.files_scanned,
        "findings": report.findings,
        "by_type": report.by_type(),
        "report_engram": report.engram_id,
    }
    if _json_out(ctx, data):
        return
    console.print(
        f"[bold]sweep[/bold] {target}: {report.files_scanned} files, {len(report.findings)} findings"
    )
    for f in report.findings[:20]:
        console.print(f"  [yellow]{f['type']:>16}[/yellow] {f['file']}:{f['line']}  {f['text']}")


def _kernel_story() -> None:
    """The 5-pillar BENE 2.0 story on a throwaway db — keyless, deterministic."""
    import tempfile
    import time as _t

    from bene.kernel import CapabilityRegistry, EngramStore, ensure_v2
    from bene.kernel.eval import Probe
    from bene.kernel.evolve import Genome, ReflectiveEvolver, promote
    from bene.kernel.harness import AutonomyPolicy, SensesManifest
    from bene.kernel.memory import GranuleStore, PollutionDetector
    from bene.kernel.trust import TrustLedger

    t0 = _t.monotonic()
    workdir = tempfile.mkdtemp(prefix="bene-demo-")
    db_path = str(Path(workdir) / "story.db")
    console.print(f"[bold cyan]BENE 2.0 story[/bold cyan]  {db_path}")

    b = _get_afs(db_path)
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)

    # Pillar foundations: an agent, traces, the ladder
    agent = b.spawn("scout")
    g = GranuleStore(store)
    turns = [
        g.write_turn(agent, "explored the auth module; found retry bug in backoff"),
        g.write_turn(agent, "wrote failing test; fix candidate A failed"),
        g.write_turn(agent, "fix candidate B passed all tests"),
    ]
    episode = g.consolidate(
        turns, summary="episode: retry bug fixed via candidate B", provenance={"agent_id": agent}
    )
    console.print(
        f"  [green]engrams[/green]      3 turns -> 1 episode ({episode[:8]}…) — the compression ladder"
    )

    # Pillar 1+2: a falsifiable probe gates an evolved candidate
    cid = b.log_tool_call(agent, "run_tests", {})
    b.complete_tool_call(cid, output={"passed": True}, status="success")
    seed = Genome(
        components={
            "memory_policy": "all",
            "retrieval_policy": "fts",
            "context_strategy": "recency",
            "tool_config": "default",
            "prompt": "solve the task",
        }
    )
    kws = ("plan", "verify", "checkpoint")

    def bench(gn):
        return {
            "quality": sum(k in gn.components["prompt"] for k in kws) / 3,
            "cost": len(gn.components["prompt"]) / 1000,
            "tokens": float(len(gn.components["prompt"].split())),
        }

    def reflect(gn, fb):
        p = gn.components["prompt"]
        for k in kws:
            if k not in p:
                return {"component": "prompt", "new_text": f"{p}; always {k}", "rationale": k}
        return {"component": "prompt", "new_text": p, "rationale": "saturated"}

    frontier = ReflectiveEvolver(store, b.conn, reflect_fn=reflect, benchmark=bench).run(
        seed, generations=2, population=2
    )
    best = max(frontier.members(), key=lambda m: m.scores["quality"])
    console.print(
        f"  [green]breeding[/green]     2 offline generations -> best quality {best.scores['quality']:.2f} (frontier {len(frontier.members())})"
    )

    gate = {
        "name": "G1_improves",
        "description": "quality must improve",
        "metric": "quality",
        "op": ">=",
        "threshold": 0.1,
        "relative_to_baseline": True,
    }
    probe = Probe("story-probe", [gate], lambda gn: bench(gn) if isinstance(gn, Genome) else gn)
    probe.register(store, b.conn, baseline=seed, subject_ref=best.engram_id)
    verdict = probe.run(best, seed, store=store, conn=b.conn)
    promote(best.engram_id, store=store, conn=b.conn)
    console.print(
        f"  [green]kill gates[/green]   probe {verdict.status} -> promotion ALLOWED (without it: PromotionBlocked)"
    )

    # Pillar 3: pollution scan (clean here)
    report = PollutionDetector(store).scan(agent)
    console.print(
        f"  [green]context OS[/green]   pollution score {report.score} — clean run, no recovery needed"
    )

    # Pillar 4: autonomy ladder
    policy = AutonomyPolicy(b.conn, store)
    policy.grant(agent, 2, granted_by="policy:demo")
    registry = CapabilityRegistry(b.conn, autonomy_check=policy.check)
    registry.register(
        "evolve.promote",
        autonomy_level=4,
        description="promote evolved artifacts",
        handler=lambda: None,
    )
    try:
        registry.dispatch("evolve.promote", agent)
    except Exception:
        console.print(
            "  [green]autonomy[/green]     L2 agent denied L4 'evolve.promote' — denial recorded as trust engram"
        )

    # Pillar 5: computed trust + senses
    summary = TrustLedger(b.conn, store).summary(agent)
    console.print(
        f"  [green]trust[/green]        composite {summary['composite']} ({summary['denials']} denial on record) — computed, never declared"
    )
    manifest = SensesManifest.generate(b)
    n_caps = len(json.loads(manifest)["capabilities"])
    console.print(
        f"  [green]senses[/green]       manifest generated from live db ({n_caps} capabilities)"
    )

    engrams = b.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]
    runs = b.conn.execute("SELECT COUNT(*) FROM experiment_runs").fetchone()[0]
    b.close()
    console.print(
        f"[bold]story complete[/bold] in {_t.monotonic() - t0:.1f}s — {engrams} engrams, {runs} experiment runs."
        f"\n  inspect: [cyan]bene experiments ls --db {db_path}[/cyan] · [cyan]bene trust {agent} --db {db_path}[/cyan]"
    )


if __name__ == "__main__":
    cli()
