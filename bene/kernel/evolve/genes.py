"""Strategy genes — control-signal-dense experience encoding (GEP/EvoMap).

A gene is NOT documentation. The GEP finding (SYNTHESIS: agent-auto-opt #03):
explanatory prose actively dilutes and hurts; what transfers is control logic —
a match signal (when does this apply), compressed strategy steps, and AVOID
warnings. Genes are versioned tier-4 engrams; merging genes unions their
control logic, never their prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyGene:
    match_signal: str  # when this gene applies (task/trace signature)
    steps: tuple[str, ...]  # compressed strategy steps, imperative
    avoid: tuple[str, ...] = ()  # AVOID warnings from failure evidence
    version: int = 1

    def encode(self) -> str:
        """Compact control-signal encoding (~target <=230 tokens, no prose)."""
        lines = [f"MATCH: {self.match_signal}"]
        lines += [f"STEP{i + 1}: {s}" for i, s in enumerate(self.steps)]
        lines += [f"AVOID: {a}" for a in self.avoid]
        lines.append(f"V: {self.version}")
        return "\n".join(lines)

    @classmethod
    def decode(cls, text: str) -> StrategyGene:
        match_signal, steps, avoid, version = "", [], [], 1
        for line in text.splitlines():
            key, _, val = line.partition(": ")
            if key == "MATCH":
                match_signal = val
            elif key.startswith("STEP"):
                steps.append(val)
            elif key == "AVOID":
                avoid.append(val)
            elif key == "V":
                version = int(val)
        return cls(match_signal, tuple(steps), tuple(avoid), version)

    @classmethod
    def merge(cls, a: StrategyGene, b: StrategyGene) -> StrategyGene:
        """Union of control logic; the broader match signal wins; version bumps."""
        match = a.match_signal if len(a.match_signal) >= len(b.match_signal) else b.match_signal
        steps = list(a.steps) + [s for s in b.steps if s not in a.steps]
        avoid = list(a.avoid) + [w for w in b.avoid if w not in a.avoid]
        return cls(match, tuple(steps), tuple(avoid), max(a.version, b.version) + 1)


@dataclass
class GenePool:
    genes: list[StrategyGene] = field(default_factory=list)

    def add(self, gene: StrategyGene) -> None:
        self.genes.append(gene)

    def matching(self, signal_text: str) -> list[StrategyGene]:
        """Cheap lexical match: a gene applies when any match-signal word
        appears in the task signature (pluggable for smarter scorers)."""
        hits = []
        for g in self.genes:
            words = {w.lower() for w in g.match_signal.split() if len(w) > 3}
            if words & {w.lower() for w in signal_text.split()}:
                hits.append(g)
        return hits
