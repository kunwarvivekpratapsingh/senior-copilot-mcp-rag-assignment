"""Document loading and text extraction.

Reads the corpus from disk, parses YAML frontmatter into typed metadata, and extracts
plain text. Markdown natively; PDF via ``pypdf`` so the pipeline handles the format
real operating procedures actually arrive in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter


@dataclass(frozen=True)
class LoadedDocument:
    """One source document with its metadata and extracted text."""

    doc_id: str
    title: str
    doc_type: str
    source_path: str
    text: str
    asset_tags: list[str] = field(default_factory=list)
    unit: str | None = None
    site: str | None = None
    last_reviewed: str | None = None
    version: str | None = None

    def metadata(self) -> dict[str, Any]:
        """Flat metadata for the index.

        Chroma metadata values must be scalars, so ``asset_tags`` is stored as a
        delimited string. The delimiters are retained on both sides so a substring
        match cannot pair "Boiler Feed Pump 10" with "Boiler Feed Pump 101".
        """
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type,
            "source_path": self.source_path,
            "asset_tags": "|" + "|".join(self.asset_tags) + "|" if self.asset_tags else "",
            "unit": self.unit or "",
            "site": self.site or "",
            "last_reviewed": self.last_reviewed or "",
            "version": self.version or "",
        }


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value in (None, ""):
        return []
    return [str(value)]


def load_markdown(path: Path) -> LoadedDocument:
    """Parse a markdown document and its YAML frontmatter."""
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    meta = post.metadata
    doc_id = str(meta.get("doc_id") or path.stem)
    return LoadedDocument(
        doc_id=doc_id,
        title=str(meta.get("title") or doc_id),
        doc_type=str(meta.get("doc_type") or "document"),
        source_path=str(path.as_posix()),
        text=post.content.strip(),
        asset_tags=_as_list(meta.get("asset_tags")),
        unit=str(meta.get("unit")) if meta.get("unit") else None,
        site=str(meta.get("site")) if meta.get("site") else None,
        last_reviewed=str(meta.get("last_reviewed")) if meta.get("last_reviewed") else None,
        version=str(meta.get("version")) if meta.get("version") else None,
    )


def load_pdf(path: Path) -> LoadedDocument:
    """Extract text from a PDF.

    PDFs carry no frontmatter, so metadata is inferred from the filename. Included
    because real procedure libraries are largely PDF, and a pipeline that only handles
    markdown would not survive contact with one.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    return LoadedDocument(
        doc_id=path.stem,
        title=path.stem.replace("-", " ").replace("_", " ").title(),
        doc_type="pdf_document",
        source_path=str(path.as_posix()),
        text=text.strip(),
    )


def load_corpus(directory: Path) -> list[LoadedDocument]:
    """Load every supported document in a directory, sorted for reproducibility."""
    documents: list[LoadedDocument] = []
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() == ".md":
            documents.append(load_markdown(path))
        elif path.suffix.lower() == ".pdf":
            documents.append(load_pdf(path))
    return documents
