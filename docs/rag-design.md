# RAG design

Ingestion and retrieval design, covering every field required by
Submission_and_Evaluation_Guidelines.md §7: source document types, ingestion flow, text
extraction, chunking strategy, chunk metadata, embedding model, vector index, hybrid
search, ranking, retrieval filters, citation construction, low-confidence handling,
prompt-injection protections, and index refresh.

> **Pending — authored in build step 5 (RAG pipeline), before the code it describes.**

Until then, the retrieval approach is summarised in
[`hld.md` ADR-03](hld.md#adr-03--hybrid-retrieval-rather-than-dense-only) and the
request-time behaviour in [`architecture.md` §5](architecture.md#5--retrieval-inside-the-same-workflow).
