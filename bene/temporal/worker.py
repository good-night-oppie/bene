"""Temporal worker bootstrap for BENE.

The worker:

1. Connects to the Temporal frontend (``--address``).
2. Initializes a :class:`bene.storage.protocol.Storage` backend (SQLite or
   Postgres).
3. Optionally wires a custom LLM/tool handler.
4. Registers :class:`bene.temporal.workflow.AgentWorkflow` and every Activity
   on a task queue.

The CLI wrapper lives in :mod:`bene.cli.main` (``bene temporal worker``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from bene.storage.protocol import BlobStore, Storage
from bene.temporal import runtime as bene_runtime

log = logging.getLogger(__name__)


async def build_worker(
    *,
    address: str,
    namespace: str = "default",
    task_queue: str = "bene-main",
    storage: Storage,
    blobs: BlobStore,
    llm_handler: Callable[[str, str, str], Awaitable[dict]] | None = None,
    tool_handler: Callable[[str, dict], Awaitable[dict]] | None = None,
    max_concurrent_workflows: int = 100,
    max_concurrent_activities: int = 50,
):
    """Connect to Temporal and return a configured ``Worker`` ready to run."""
    from temporalio.client import Client
    from temporalio.worker import Worker

    from bene.temporal.activities import ALL_ACTIVITIES
    from bene.temporal.workflow import AgentWorkflow

    bene_runtime.configure(
        storage=storage,
        blobs=blobs,
        llm_handler=llm_handler,
        tool_handler=tool_handler,
    )

    log.info(
        "Connecting Temporal worker: address=%s namespace=%s queue=%s",
        address,
        namespace,
        task_queue,
    )
    client = await Client.connect(address, namespace=namespace)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[AgentWorkflow],
        activities=ALL_ACTIVITIES,  # type: ignore[arg-type]
        max_concurrent_workflow_tasks=max_concurrent_workflows,
        max_concurrent_activities=max_concurrent_activities,
    )
    return worker


async def run_worker(
    *,
    address: str,
    namespace: str = "default",
    task_queue: str = "bene-main",
    sqlite_db: str | None = None,
    postgres_dsn: str | None = None,
    llm_handler: Callable[[str, str, str], Awaitable[dict]] | None = None,
    tool_handler: Callable[[str, dict], Awaitable[dict]] | None = None,
) -> None:
    """High-level helper used by the ``bene temporal worker`` CLI.

    Picks the storage backend based on which connection details were
    provided, then runs the Temporal worker until cancelled.
    """
    storage: Storage
    blobs: BlobStore

    if postgres_dsn:
        from bene.storage.postgres import PostgresStorage

        pg = await PostgresStorage.connect(postgres_dsn)
        storage = pg
        blobs = pg.blobs  # type: ignore[assignment]
    else:
        from bene.storage.sqlite import SqliteStorage

        sql = SqliteStorage(db_path=sqlite_db or "bene.db")
        storage = sql
        blobs = sql.blobs  # type: ignore[assignment]

    worker = await build_worker(
        address=address,
        namespace=namespace,
        task_queue=task_queue,
        storage=storage,
        blobs=blobs,
        llm_handler=llm_handler,
        tool_handler=tool_handler,
    )

    log.info("bene worker ready: queue=%s", task_queue)
    try:
        await worker.run()
    finally:
        await storage.close()


def main_cli(
    *,
    address: str,
    namespace: str = "default",
    task_queue: str = "bene-main",
    sqlite_db: str | None = None,
    postgres_dsn: str | None = None,
) -> None:
    """Synchronous entrypoint for ``bene temporal worker``."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(
        run_worker(
            address=address,
            namespace=namespace,
            task_queue=task_queue,
            sqlite_db=sqlite_db,
            postgres_dsn=postgres_dsn,
        )
    )
