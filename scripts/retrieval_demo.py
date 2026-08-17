"""Print what retrieval returns for the acceptance scenario.

    python -m rag.ingestion.cli --docs ./rag/documents --reset
    python scripts/retrieval_demo.py

Exists so the table in ``docs/rag-design.md`` §10a is reproducible rather than
asserted, and so the two scores can be seen side by side: ``score`` is the fused rank
position the GUI displays, ``similarity`` is the absolute relevance the confidence
threshold reads. Confusing the two made the low-confidence path unreachable once
already.
"""

from __future__ import annotations

import argparse

from rag.ingestion import DocumentIndex, build_embedder
from rag.retrieval import RetrievalService

SCENARIO = (
    "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last "
    "90 days, identify likely contributing factors, retrieve the relevant operating "
    "procedure, and provide recommended actions with source evidence."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=SCENARIO)
    parser.add_argument(
        "--asset", default="Boiler Feed Pump 101",
        help="Metadata filter, as the orchestrator supplies it from an earlier tool call",
    )
    parser.add_argument("--persist", default=".chroma")
    parser.add_argument("--embedder", default="hashing")
    args = parser.parse_args(argv)

    index = DocumentIndex(build_embedder(args.embedder), persist_path=args.persist)
    if index.count == 0:
        print("The index is empty. Run: python -m rag.ingestion.cli --reset")
        return 1

    result = RetrievalService(index).search(args.query, asset=args.asset or None)

    # ASCII only: this prints on a Windows console by default, where a stray ellipsis
    # character renders as mojibake.
    print(f"query:            {args.query[:80]}...")
    print(f"asset filter:     {args.asset or '(none)'}")
    print(f"low_confidence:   {result.low_confidence}")
    print(f"best_score:       {result.best_score:.2f}  (threshold 0.35)")
    print()
    print(f"{'rank':>4}  {'score':>5}  {'sim':>5}  citation")
    for rank, chunk in enumerate(result.chunks, start=1):
        print(f"{rank:>4}  {chunk.score:>5.2f}  {chunk.similarity:>5.2f}  {chunk.citation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
