# Known limitations

Honest scope boundaries. Every item here is a deliberate choice made under a time box,
not an oversight — each states what would be done differently with more time.

---

## Architecture and scale

**Local vector store.** Retrieval uses Chroma embedded in the backend process, persisted
to a volume. This is right for a ten-document demo corpus and wrong for a real plant with
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

**Embeddings are lexical by default.** `EMBEDDING_MODEL=hashing` uses a deterministic
BLAKE2b feature hash rather than a trained model, so the "dense" half of the hybrid is
weaker at paraphrase than it looks on paper. This was chosen over baking
sentence-transformers weights into the image: that would add gigabytes and a model
download to a clean clone, and an evaluator's first `docker compose up` matters more
than marginal recall. The trained embedder is one environment variable away
(`EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2` with the `rag-transformers`
extra), and BM25 covers the exact-term cases that dominate operator questions.

## Operational

**GitHub integration runs mocked by default.** `GITHUB_MOCK=true` uses an in-memory
backend. The real REST backend exists behind the same interface, but the demo path does
not require a GitHub token — and a demo that writes to a real repository is a demo that
cannot be run twice.

**One image for four Python services.** The simulator, both MCP servers, and the backend
share a single image and differ only by command. It is a few megabytes larger per
service than purpose-built images would be, in exchange for one dependency layer, one
build, and one place where the Python version is pinned.

## Testing

**The LLM path is mocked everywhere.** Every test runs against either the deterministic
provider or a stubbed Anthropic client, including the end-to-end test. That makes the
suite fast, free, and repeatable, and it means no test asserts on the quality of
generated prose — only on the plan structure, the request shape, the refusal path, and
the citations. Model output quality is verified by hand, in the demo.

**No frontend component tests.** The GUI is type-checked (`tsc --noEmit`) and linted, and
its data contracts are exercised end to end through the same endpoints it calls — the E2E
test parses the SSE stream exactly as `api.ts` does, including the CRLF normalisation that
a naive parser gets wrong. What is not covered is rendering: no Vitest or Testing Library
suite asserts that a citation chip appears or that the confirmation dialog blocks. With
more time that is the first gap to close, because the write-confirmation dialog is a
safety control and safety controls deserve their own tests.

**Type checking covers shipped code, not tests.** `mypy` runs over every package but
excludes `tests/`, which are full of decoded JSON that mypy sees as `dict[str, object]`
and rejects at almost every access. Annotating each one would add noise to the
most-read files in the repository to re-check what the next line asserts at runtime.
