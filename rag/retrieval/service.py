"""Hybrid retrieval.

Two rankings, fused. BM25 finds passages that share the query's words; the vector
index finds passages that are close in embedding space. Fusing them recovers the
cases each misses alone — an exact term match the vectors dilute, and a paraphrase
BM25 cannot see.

Fusion is **reciprocal rank fusion** rather than a weighted score sum. Scores from the
two systems are not on a common scale — BM25 is unbounded and corpus-dependent, cosine
similarity is bounded — so summing them means arbitrarily weighting one by whatever
its scale happens to be. RRF uses only the *rank*, which is comparable by
construction and needs no per-corpus tuning.

Below the confidence threshold the service reports ``low_confidence`` rather than
returning its best weak guess, so the composer can say no relevant procedure was
found instead of dressing up a poor match as an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rank_bm25 import BM25Okapi

from ..ingestion.embedder import tokenize
from ..ingestion.indexer import DocumentIndex

# Standard RRF constant. Damps the influence of the very top ranks so a single
# system cannot dominate the fusion on its own.
RRF_K = 60

DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.35

# Words carrying no topical signal. Excluded when measuring term coverage so a query
# is judged on its content words rather than its grammar.
STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "of", "on", "or", "should", "that", "the", "their", "there", "these", "this", "to", "was", "were", "what", "when", "where", "which", "who", "why", "will", "with", "would", "you", "your"]
)


def content_terms(text: str) -> set[str]:
    """The distinctive words of a query — what a passage must contain to be relevant."""
    return {t for t in tokenize(text) if t not in STOPWORDS and len(t) > 2}


def term_coverage(query: str, passage: str) -> float:
    """Share of the query's content terms that appear in the passage.

    This is the confidence signal, not cosine.

    Cosine over a lexical embedding is compressed: in testing, a genuinely relevant
    passage scored 0.26 and a completely unrelated query scored 0.27, so no threshold
    on it could separate the two. Term coverage is directly interpretable — "the
    passage contains four of the six things you asked about" — and it collapses to
    zero for an off-corpus query, which is exactly the behaviour the low-confidence
    path needs.
    """
    terms = content_terms(query)
    if not terms:
        return 0.0
    present = content_terms(passage)
    return len(terms & present) / len(terms)


@dataclass(frozen=True)
class RetrievedChunk:
    """One passage, with everything the GUI and the citation need.

    Two scores, because they answer different questions and conflating them was a
    bug. ``score`` is the fused rank position — how this passage compares to the
    others that came back. ``similarity`` is absolute relevance, the greater of
    cosine and term coverage. Only the second can say "nothing here is any good".
    """

    chunk_id: str
    doc_id: str
    title: str
    section: str
    citation: str
    text: str
    score: float
    similarity: float
    source_path: str
    vector_rank: int | None = None
    lexical_rank: int | None = None

    @property
    def marker(self) -> str:
        """The inline marker the composer emits into the answer."""
        return f"[source: {self.citation}]"

    def excerpt(self, limit: int = 320) -> str:
        body = self.text.strip().replace("\n", " ")
        return body if len(body) <= limit else body[:limit].rsplit(" ", 1)[0] + "…"


@dataclass(frozen=True)
class RetrievalResult:
    """The outcome of one retrieval, including the case where nothing was good enough.

    ``best_score`` is the best **absolute relevance** across the returned passages —
    the greater of cosine similarity and term coverage — never the fused rank score.

    That distinction is load-bearing. Reciprocal rank fusion is a ranking method: its
    top result always scores near the maximum whether or not anything relevant was
    found. Thresholding on it made the low-confidence path unreachable, which is how
    the bug was found.
    """

    query: str
    chunks: list[RetrievedChunk]
    low_confidence: bool
    best_score: float
    filters_applied: dict[str, Any] = field(default_factory=dict)

    @property
    def doc_ids(self) -> list[str]:
        """For the graded ``retrieved_doc_ids`` log field."""
        return sorted({chunk.doc_id for chunk in self.chunks})


class RetrievalService:
    """Hybrid search over the document index."""

    def __init__(
        self,
        index: DocumentIndex,
        *,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        self._index = index
        self._top_k = top_k
        self._min_score = min_score
        self._bm25: BM25Okapi | None = None
        self._ids: list[str] = []
        self._texts: list[str] = []
        self._metadatas: list[dict[str, Any]] = []

    def _ensure_lexical_index(self) -> None:
        if self._bm25 is not None:
            return
        self._ids, self._texts, self._metadatas = self._index.all_chunks()
        if self._texts:
            # The same tokeniser as the embedder, so both halves of the hybrid see
            # identical tokens and their rankings are genuinely comparable.
            self._bm25 = BM25Okapi([tokenize(text) for text in self._texts])

    def refresh(self) -> None:
        """Drop the cached lexical index. Call after re-ingesting."""
        self._bm25 = None

    @staticmethod
    def _matches_filters(metadata: dict[str, Any], asset: str | None, doc_type: str | None) -> bool:
        if doc_type and metadata.get("doc_type") != doc_type:
            return False
        if asset:
            # Tags are stored delimiter-wrapped, so this cannot match a prefix:
            # "|Boiler Feed Pump 101|" does not contain "|Boiler Feed Pump 10|".
            tags = str(metadata.get("asset_tags") or "")
            if f"|{asset}|" not in tags:
                return False
        return True

    def search(
        self,
        query: str,
        *,
        asset: str | None = None,
        doc_type: str | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """Retrieve passages relevant to a query.

        ``asset`` is the join that makes RAG part of the same workflow as the tool
        chain: once an earlier step has resolved which asset the question is about,
        retrieval narrows to documents tagged for it instead of searching everything.
        """
        top_k = top_k or self._top_k
        self._ensure_lexical_index()
        filters = {k: v for k, v in {"asset": asset, "doc_type": doc_type}.items() if v}

        if not self._texts:
            return RetrievalResult(query, [], low_confidence=True, best_score=0.0,
                                   filters_applied=filters)

        # -- vector ranking -------------------------------------------------- #
        # Over-fetch, because metadata filtering happens after retrieval and would
        # otherwise leave fewer than top_k survivors.
        vector_hits = self._index.query(
            self._index.embedder.embed([query])[0], top_k=max(top_k * 4, 20)
        )
        vector_ranked = [
            (chunk_id, text, metadata, score)
            for chunk_id, text, metadata, score in vector_hits
            if self._matches_filters(metadata, asset, doc_type)
        ]

        # -- lexical ranking -------------------------------------------------- #
        lexical_ranked: list[tuple[str, str, dict[str, Any], float]] = []
        if self._bm25 is not None:
            scores = self._bm25.get_scores(tokenize(query))
            order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            for i in order[: max(top_k * 4, 20)]:
                if scores[i] <= 0:
                    continue
                if not self._matches_filters(self._metadatas[i], asset, doc_type):
                    continue
                lexical_ranked.append(
                    (self._ids[i], self._texts[i], self._metadatas[i], float(scores[i]))
                )

        # -- reciprocal rank fusion, for ORDERING ----------------------------- #
        fused: dict[str, float] = {}
        record: dict[str, tuple[str, dict[str, Any]]] = {}
        vector_rank: dict[str, int] = {}
        lexical_rank: dict[str, int] = {}
        # Raw cosine per chunk, kept separately because relevance is an absolute
        # question and rank fusion cannot answer it.
        similarity: dict[str, float] = {}

        for rank, (chunk_id, text, metadata, score) in enumerate(vector_ranked, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            record[chunk_id] = (text, metadata)
            vector_rank[chunk_id] = rank
            similarity[chunk_id] = score

        for rank, (chunk_id, text, metadata, _) in enumerate(lexical_ranked, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            record.setdefault(chunk_id, (text, metadata))
            lexical_rank[chunk_id] = rank
            similarity.setdefault(chunk_id, 0.0)

        if not fused:
            return RetrievalResult(query, [], low_confidence=True, best_score=0.0,
                                   filters_applied=filters)

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

        # RRF scores are tiny by construction (two systems, best case ~2/61). Scaling
        # against the theoretical maximum makes them readable — but this is a
        # *position* score, never a relevance score.
        theoretical_max = 2.0 / (RRF_K + 1)
        chunks = [
            RetrievedChunk(
                chunk_id=chunk_id,
                doc_id=str(record[chunk_id][1].get("doc_id", "")),
                title=str(record[chunk_id][1].get("title", "")),
                section=str(record[chunk_id][1].get("section", "")),
                citation=str(record[chunk_id][1].get("citation", "")),
                text=record[chunk_id][0],
                score=round(min(raw / theoretical_max, 1.0), 4),
                similarity=round(
                    max(
                        similarity.get(chunk_id, 0.0),
                        term_coverage(query, record[chunk_id][0]),
                    ),
                    4,
                ),
                source_path=str(record[chunk_id][1].get("source_path", "")),
                vector_rank=vector_rank.get(chunk_id),
                lexical_rank=lexical_rank.get(chunk_id),
            )
            for chunk_id, raw in ordered
        ]

        # Confidence is judged on the best ABSOLUTE relevance across the returned
        # passages — never on the fused rank score, whose top entry is always near the
        # maximum whether or not anything relevant was found.
        best_relevance = max((c.similarity for c in chunks), default=0.0)
        return RetrievalResult(
            query=query,
            chunks=chunks,
            low_confidence=best_relevance < self._min_score,
            best_score=best_relevance,
            filters_applied=filters,
        )
