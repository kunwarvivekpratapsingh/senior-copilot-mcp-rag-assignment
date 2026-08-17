"""Vector index construction.

Chroma runs **embedded in-process** rather than as a separate service. The corpus is
small, and an embedded index removes a container, a network hop, and a failure mode
from a demo that has to work on someone else's machine from a clean clone. Moving to
a hosted vector store is a change to this module alone.

Embeddings are supplied by us rather than by Chroma's default embedding function,
which would otherwise download an ONNX model on first use — the same
network-dependency problem the embedder module exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from .chunker import Chunk
from .embedder import Embedder
from .loader import LoadedDocument

DEFAULT_COLLECTION = "operations-docs"


@dataclass
class IndexStats:
    documents: int
    chunks: int
    collection: str
    embedder: str
    dimensions: int


class DocumentIndex:
    """The persisted chunk store behind retrieval."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        persist_path: str | Path = ".chroma",
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        self._embedder = embedder
        self._collection_name = collection_name
        self._client = chromadb.PersistentClient(
            path=str(persist_path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            # Vectors are L2-normalised, so cosine is the right space and the score
            # is directly interpretable as similarity.
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    @property
    def count(self) -> int:
        return int(self._collection.count())

    def reset(self) -> None:
        """Drop and recreate the collection.

        Ingestion is a full rebuild rather than an incremental update: the corpus is
        small, and a rebuild cannot leave orphaned chunks behind when a document is
        edited or deleted.
        """
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name, metadata={"hnsw:space": "cosine"}
        )

    def add(self, pairs: list[tuple[LoadedDocument, Chunk]]) -> None:
        if not pairs:
            return
        texts = [chunk.text for _, chunk in pairs]
        vectors = self._embedder.embed(texts)
        self._collection.add(
            ids=[chunk.chunk_id for _, chunk in pairs],
            embeddings=vectors,  # type: ignore[arg-type]
            documents=texts,
            metadatas=[
                {
                    **document.metadata(),
                    "section": chunk.section,
                    "section_anchor": chunk.section_anchor,
                    "chunk_index": chunk.chunk_index,
                    "citation": chunk.citation,
                }
                for document, chunk in pairs
            ],
        )

    def all_chunks(self) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        """Every chunk, for building the lexical index.

        Loading the whole collection is reasonable at this corpus size and keeps BM25
        exactly in step with the vector store. At a scale where it is not, BM25 would
        move to a persisted inverted index — noted in known-limitations.
        """
        result = self._collection.get(include=["documents", "metadatas"])
        return (
            list(result.get("ids") or []),
            [str(d) for d in (result.get("documents") or [])],
            [dict(m) for m in (result.get("metadatas") or [])],
        )

    def query(
        self, vector: list[float], top_k: int, where: dict[str, Any] | None = None
    ) -> list[tuple[str, str, dict[str, Any], float]]:
        """Nearest neighbours as ``(id, text, metadata, similarity)``.

        Chroma returns cosine *distance*; similarity is ``1 - distance`` so a larger
        number means a better match, which is what every caller expects.
        """
        result = self._collection.query(
            query_embeddings=[vector],  # type: ignore[arg-type]
            n_results=min(top_k, max(self.count, 1)),
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            (str(i), str(d), dict(m), 1.0 - float(dist))
            for i, d, m, dist in zip(ids, documents, metadatas, distances, strict=False)
        ]


def build_index(
    documents: list[LoadedDocument],
    pairs: list[tuple[LoadedDocument, Chunk]],
    embedder: Embedder,
    *,
    persist_path: str | Path = ".chroma",
    collection_name: str = DEFAULT_COLLECTION,
    reset: bool = True,
) -> IndexStats:
    index = DocumentIndex(
        embedder, persist_path=persist_path, collection_name=collection_name
    )
    if reset:
        index.reset()
    index.add(pairs)
    return IndexStats(
        documents=len(documents),
        chunks=len(pairs),
        collection=collection_name,
        embedder=embedder.name,
        dimensions=embedder.dimensions,
    )
