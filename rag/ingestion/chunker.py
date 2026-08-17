"""Header-aware chunking.

Chunks never straddle a markdown heading, so every chunk belongs to exactly one
nameable section. That is what makes a citation useful: ``[source: OP-BFP-101]``
tells a reader which document, but ``[source: OP-BFP-101#abnormal-condition-discharge-
pressure-low]`` tells them where to look.

A section longer than the token budget is split on paragraph boundaries with overlap,
so a passage spanning the split is still retrievable from either half.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .loader import LoadedDocument

# Tokens are approximated as words × 1.3. Exact counting would need the target
# model's tokeniser, which is not worth a dependency here — chunk size only needs to
# be roughly right, and being slightly conservative costs nothing.
WORDS_PER_TOKEN = 1 / 1.3

DEFAULT_MAX_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 50

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)

# Sections that are navigation rather than content. They are short, dense with other
# documents' titles and keywords, and therefore match almost any query while carrying
# no answer — in early testing a "Related documents" list outranked the actual
# procedure for its own topic. Excluding them at ingestion is more honest than
# down-weighting them at query time, because they are genuinely not retrievable
# content.
BOILERPLATE_HEADINGS = frozenset(
    {
        "related documents",
        "related",
        "references",
        "see also",
        "contact",
        "revision history",
        "document control",
        "parts affected",
    }
)


def is_boilerplate(heading: str) -> bool:
    return heading.strip().lower() in BOILERPLATE_HEADINGS


@dataclass(frozen=True)
class Chunk:
    """A retrievable passage with everything a citation needs."""

    chunk_id: str
    doc_id: str
    section: str
    section_anchor: str
    text: str
    chunk_index: int

    @property
    def citation(self) -> str:
        """The inline marker the composer emits."""
        return f"{self.doc_id}#{self.section_anchor}" if self.section_anchor else self.doc_id


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) / WORDS_PER_TOKEN)


def slugify(heading: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", heading.lower())
    return re.sub(r"\s+", "-", slug.strip())[:64]


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, body)`` pairs.

    Content before the first heading is kept under a "Preamble" heading rather than
    discarded — in a real procedure that is often the scope statement.
    """
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [("Document", text.strip())]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("Preamble", preamble))

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((heading, body))
    return sections


def _split_long_section(
    body: str, max_tokens: int, overlap_tokens: int
) -> list[str]:
    """Split an over-long section on paragraph boundaries, with overlap."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[str] = []
    current: list[str] = []

    for paragraph in paragraphs:
        candidate = [*current, paragraph]
        if estimate_tokens("\n\n".join(candidate)) > max_tokens and current:
            parts.append("\n\n".join(current))
            # Carry the tail of the previous part forward so a passage spanning the
            # boundary remains retrievable from either side.
            carried: list[str] = []
            for previous in reversed(current):
                if estimate_tokens("\n\n".join([previous, *carried])) > overlap_tokens:
                    break
                carried.insert(0, previous)
            current = [*carried, paragraph]
        else:
            current = candidate

    if current:
        parts.append("\n\n".join(current))
    return parts


def chunk_document(
    document: LoadedDocument,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk one document, respecting heading boundaries."""
    chunks: list[Chunk] = []
    index = 0

    for heading, body in split_sections(document.text):
        if is_boilerplate(heading):
            continue
        bodies = (
            [body]
            if estimate_tokens(body) <= max_tokens
            else _split_long_section(body, max_tokens, overlap_tokens)
        )
        for part in bodies:
            # Prefix the document title and section heading onto the chunk text —
            # "contextual chunk headers". Two reasons:
            #
            # 1. Queries are often phrased as topics ("lockout tagout procedure")
            #    rather than as sentences, and the topic is usually in the heading.
            # 2. A document's title frequently appears in NO chunk body. The
            #    lockout/tagout procedure's title lives only in its H1, whose section
            #    body is empty, so before this change no chunk contained the words
            #    "lockout" or "tagout" and the document was effectively unfindable by
            #    its own name.
            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id}::{index}",
                    doc_id=document.doc_id,
                    section=heading,
                    section_anchor=slugify(heading),
                    text=f"{document.title} — {heading}\n\n{part}",
                    chunk_index=index,
                )
            )
            index += 1

    return chunks


def chunk_corpus(
    documents: list[LoadedDocument], **kwargs: int
) -> list[tuple[LoadedDocument, Chunk]]:
    return [(doc, chunk) for doc in documents for chunk in chunk_document(doc, **kwargs)]
