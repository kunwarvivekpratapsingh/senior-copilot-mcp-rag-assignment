"""Retrieval: hybrid search, citations, and the document trust boundary."""

from .citations import Citation, build_citations, verify_citations
from .guard import TRUST_BOUNDARY_INSTRUCTION, scan, wrap_for_prompt
from .service import RetrievalResult, RetrievalService, RetrievedChunk

__all__ = [
    "TRUST_BOUNDARY_INSTRUCTION", "Citation", "RetrievalResult", "RetrievalService",
    "RetrievedChunk", "build_citations", "scan", "verify_citations", "wrap_for_prompt",
]
