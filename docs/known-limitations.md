# Known limitations

Honest scope boundaries. Every item here is a deliberate choice made under a time box,
not an oversight — each states what would be done differently with more time.

> Reviewed and finalised in the documentation close-out step. Items are added as they
> are encountered during the build.

---

## Architecture and scale

**Local vector store.** Retrieval uses Chroma running as a single container with a local
volume. This is right for a ten-document demo corpus and wrong for a real plant with
thousands of procedures. At that scale the answer is pgvector alongside the operational
database, or a managed vector service, with an ingestion pipeline that runs on document
change rather than on demand.

**No multi-tenancy.** There is one implicit tenant. Real deployment would need a site or
plant identifier threaded through retrieval filters and tool authorisation, so an
operator at one site cannot read another's alarms.

**No horizontal scaling.** The orchestrator keeps conversation and trace state in
process memory. Running more than one replica would need that state moved to Redis or a
database. The interface is already narrow enough to make the swap contained.

**Plans are fixed once generated.** The orchestrator does not replan mid-execution. If
step 2 reveals that a different tool would have been better, it finishes the original
plan and reports the gap. Replanning was traded away deliberately for an inspectable,
testable plan object (see ADR-02); a production system would likely want both.

## Security

**Static bearer token on the Alarm API.** The simulator authenticates with a shared
token from configuration. A real source system would use OAuth client credentials with
rotation, and the MCP server would refresh rather than hold a long-lived secret.

**No authentication on the copilot itself.** The GUI-to-backend hop is unauthenticated,
which is acceptable for a local demo and unacceptable anywhere else. Adding it would not
change the architecture — the trust boundary that matters (credentials living only in
the MCP servers) is already in place.

**Prompt-injection defence is not proof.** Retrieved content is wrapped as inert data
and regression-tested against a deliberately poisoned document. That raises the cost of
an attack; it does not eliminate the class. Defence in depth would add output scanning
and a stricter capability boundary on what the composer is permitted to emit.

## Retrieval quality

**Ranking is fusion, not reranking.** BM25 and dense rankings are combined by reciprocal
rank fusion. There is no cross-encoder reranking pass, which would measurably improve
precision at the top of the list. It was scoped out as a fast follow-up rather than
half-built.

**Chunking is structural, not semantic.** Chunks respect markdown headings and a token
budget. A semantic chunker that split on topic shifts would produce better passages for
long unstructured documents; the corpus here is well-structured enough that the
difference is small.

## Data

**The alarm data is synthetic and deliberately shaped.** The seed generator engineers
specific patterns — a recurring co-occurring pair on Boiler Feed Pump 101, flood bursts
in Unit 2, stale alarms in NorthPlant Unit 1 — because the supplied Postman chaining
collection asserts non-empty results for those cases. Real alarm data is messier, and
correlation on it would need statistical significance testing rather than raw
co-occurrence counts.

## Operational

**Image size.** The RAG image bakes sentence-transformers weights in at build time so
that runtime needs no network. This trades a large image for offline capability, which
is the right trade for a demo that must work on an assessor's machine without
assumptions about connectivity.

**GitHub integration runs mocked by default.** `GITHUB_MOCK=true` uses an in-memory
backend. The real REST backend exists behind the same interface and is exercised by its
own tests, but the demo path does not require a GitHub token.
