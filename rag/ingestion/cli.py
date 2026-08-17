"""Ingestion command line.

    python -m rag.ingestion.cli --docs ./rag/documents --reset

Ingestion is a full rebuild rather than an incremental update. The corpus is small,
and a rebuild cannot leave orphaned chunks behind when a document is edited or
removed — which an incremental path silently would.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .chunker import DEFAULT_MAX_TOKENS, DEFAULT_OVERLAP_TOKENS, chunk_corpus
from .embedder import build_embedder
from .indexer import DEFAULT_COLLECTION, build_index
from .loader import load_corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", default="./rag/documents", help="corpus directory")
    parser.add_argument("--persist", default=".chroma", help="index directory")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument(
        "--embedder", default="hashing",
        help="'hashing' (default, no download) or a sentence-transformers model name",
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--overlap-tokens", type=int, default=DEFAULT_OVERLAP_TOKENS)
    parser.add_argument("--reset", action="store_true", help="rebuild from empty")
    args = parser.parse_args(argv)

    directory = Path(args.docs)
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 1

    documents = load_corpus(directory)
    if not documents:
        print(f"error: no documents found in {directory}", file=sys.stderr)
        return 1

    pairs = chunk_corpus(
        documents, max_tokens=args.max_tokens, overlap_tokens=args.overlap_tokens
    )
    stats = build_index(
        documents,
        pairs,
        build_embedder(args.embedder),
        persist_path=args.persist,
        collection_name=args.collection,
        reset=args.reset,
    )

    print(f"Ingested {stats.documents} documents into '{stats.collection}'")
    print(f"  chunks:   {stats.chunks}")
    print(f"  embedder: {stats.embedder} ({stats.dimensions} dimensions)")
    print(f"  index:    {args.persist}")

    per_document: dict[str, int] = {}
    for document, _ in pairs:
        per_document[document.doc_id] = per_document.get(document.doc_id, 0) + 1
    print("\n  chunks per document:")
    for doc_id, count in sorted(per_document.items()):
        print(f"    {doc_id:20s} {count:3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
