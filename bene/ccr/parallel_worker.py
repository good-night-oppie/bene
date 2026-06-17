"""Detached worker for agent_parallel.

Runs as a separate process so the MCP server / Claude Code caller can
return immediately after dispatching parallel agents. The MCP host's
request timeout (5 min for Claude Code) no longer bounds how long the
agents may run.

Spec JSON shape:
    [{"agent_id": "...", "prompt": "..."}, ...]

The agent rows are already created in the DB by the MCP handler before
this worker is launched; this module only drives execution.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from bene.ccr.runner import ClaudeCodeRunner
from bene.config import runner_kwargs_from_config_file
from bene.core import Bene
from bene.router.tier import TierRouter


async def _run(db_path: str, config_file: str, spec_path: str) -> None:
    afs = Bene(db_path=db_path)
    router = TierRouter.from_config(config_file)
    runner = ClaudeCodeRunner(
        afs=afs,
        router=router,
        **runner_kwargs_from_config_file(config_file),
    )

    spec = json.loads(Path(spec_path).read_text())
    if not isinstance(spec, list):
        raise ValueError(f"Spec must be a JSON list, got {type(spec).__name__}")

    async def _one(task: dict) -> None:
        agent_id = task["agent_id"]
        prompt = task["prompt"]
        try:
            await runner.run_agent(agent_id, prompt)
        except Exception as e:  # noqa: BLE001
            # Runner already records failure on the agent row; log for the
            # worker's own log file so operators can diff against agent state.
            logging.getLogger("bene.parallel_worker").exception("Agent %s failed: %s", agent_id, e)

    await asyncio.gather(*[_one(t) for t in spec], return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="BENE agent_parallel detached worker")
    parser.add_argument("--db", required=True, help="Path to bene.db")
    parser.add_argument("--config-file", required=True, help="bene.yaml path")
    parser.add_argument("--spec", required=True, help="Path to JSON task spec")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    asyncio.run(_run(args.db, args.config_file, args.spec))


if __name__ == "__main__":
    main()
