"""Oppie Bug Triage Benchmark — calibrated L3 triage-decision dataset.

Eight-objective Pareto benchmark plugging into bene MetaHarness search. Built
from a calibrated 152-row JSONL corpus (Synthetic Reality Architect pipeline)
plus the OFS-124960 modal-collapse production observation.
"""

from bene.benchmarks.bug_triage.benchmark import OppieBugTriageBenchmark

__all__ = ["OppieBugTriageBenchmark"]
