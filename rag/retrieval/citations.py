"""Citation construction.

A citation has to do two jobs: appear inline in the answer compactly, and give the
GUI enough to render a panel a reader can verify against. Those are different shapes,
so both are produced from one source.

Document-level citations are not enough. ``[source: OP-BFP-101]`` points at a
procedure; ``[source: OP-BFP-101#abnormal-condition-discharge-pressure-low]`` points
at the paragraph, which is the difference between a claim a reader can check and one
they have to take on trust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .service import RetrievalResult, RetrievedChunk

CITATION_PATTERN = re.compile(r"\[source:\s*([^\]]+)\]")
TOOL_CITATION_PATTERN = re.compile(r"\[tool:\s*([^\]]+)\]")


@dataclass(frozen=True)
class Citation:
    """One evidence entry, as the GUI renders it."""

    citation: str
    doc_id: str
    title: str
    section: str
    score: float
    excerpt: str
    source_path: str
    suspicious: bool = False

    @property
    def marker(self) -> str:
        return f"[source: {self.citation}]"


def build_citations(result: RetrievalResult) -> list[Citation]:
    from .guard import scan

    return [
        Citation(
            citation=chunk.citation,
            doc_id=chunk.doc_id,
            title=chunk.title,
            section=chunk.section,
            score=chunk.score,
            excerpt=chunk.excerpt(),
            source_path=chunk.source_path,
            suspicious=scan(chunk.text).suspicious,
        )
        for chunk in result.chunks
    ]


def extract_source_citations(answer: str) -> list[str]:
    """Pull ``[source: …]`` markers out of composed text."""
    return [m.strip() for m in CITATION_PATTERN.findall(answer)]


def extract_tool_citations(answer: str) -> list[str]:
    """Pull ``[tool: …]`` markers out of composed text."""
    return [m.strip() for m in TOOL_CITATION_PATTERN.findall(answer)]


def verify_citations(answer: str, chunks: list[RetrievedChunk]) -> tuple[list[str], list[str]]:
    """Split the answer's source citations into ``(valid, hallucinated)``.

    A citation naming a document that was never retrieved is worse than no citation:
    it looks like evidence while being fabricated. Checking is cheap, so it is checked.
    """
    available = {chunk.citation for chunk in chunks} | {chunk.doc_id for chunk in chunks}
    cited = extract_source_citations(answer)
    valid = [c for c in cited if c in available or c.split("#")[0] in available]
    hallucinated = [c for c in cited if c not in valid]
    return valid, hallucinated
