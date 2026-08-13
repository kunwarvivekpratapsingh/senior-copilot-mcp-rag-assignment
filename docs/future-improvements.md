# Future improvements

What this would need to become a production system, in the order I would do it. Each
item names the problem it solves rather than the technology it adds — an improvement
list that reads as a shopping list is a wish, not a plan.

Companion to [`known-limitations.md`](known-limitations.md), which says what the system
deliberately does not do today.

---

## Near term — the first week after this submission

**Frontend component tests.** The write-confirmation dialog is a safety control with no
test that asserts it renders or blocks. Vitest plus Testing Library, starting with the
dialog and the citation-chip parser, then the loading/empty/error states of each panel.
This is first on the list because it is the only place where a control the brief cares
about is verified only by hand.

**Replanning after a failed step.** The orchestrator executes a plan and reports gaps;
it never revises. When `search_assets` returns three candidate pumps rather than one, the
right behaviour is to ask the user which, not to take `results[0]`. The plan object is
already inspectable, so this is a loop around the executor plus a `clarification`
event — not an architectural change.

**Cross-encoder reranking.** Retrieval fuses BM25 and dense rankings but never reranks.
A small cross-encoder over the top 20 fused candidates would measurably improve precision
at position 1, which is the position that actually gets cited.

**Per-tool authorisation.** Every discovered tool is currently callable by any request.
A real deployment needs a policy layer between the planner and the invoker: which roles
may call which tools, with the write tools defaulting to deny.

## Medium term — what changes when it leaves one machine

**Externalise conversation and trace state.** Both live in process memory, which is why
the backend cannot run more than one replica. Moving them to Redis (conversations, with a
TTL) and Postgres (traces, queryable) makes the backend horizontally scalable and makes
traces survive a restart — the latter matters more than it sounds, because a trace is the
evidence for an answer someone acted on.

**pgvector instead of embedded Chroma.** At a real plant's corpus size — thousands of
procedures, revised continuously — an in-process index rebuilt on startup stops being
viable. pgvector alongside the operational database keeps documents and their metadata in
one queryable place, and lets retrieval filters become SQL predicates rather than
post-filtering.

**Incremental, event-driven ingestion.** Today ingestion is a full rebuild triggered by
hand or by container start. A document management system emits change events; ingestion
should consume them, re-chunk only what changed, and record a per-document version so an
answer can say *which revision* it cited.

**Real embeddings by default.** The hashing embedder is a deliberate trade for a clean
clone (DD-07). In an environment with a model server available, the default flips, and
the lexical embedder becomes the offline fallback rather than the norm.

**OAuth client credentials for the Alarm API.** The static bearer token is the weakest
part of the security story. The MCP server should acquire and refresh a short-lived token
rather than hold a long-lived one, which also removes the secret from the environment.

## Longer term — what a second team would need

**Multi-tenancy.** A site or plant identifier threaded through retrieval filters and tool
authorisation, so an operator at one site cannot read another's alarms. This is invasive
by nature: every tool signature, every retrieval filter, and the trace model all change,
which is exactly why it should be done before there are two tenants rather than after.

**An evaluation harness for answer quality.** There is currently no automated measure of
whether an answer is *good* — only that it is structurally correct and correctly cited. A
labelled set of operator questions with expected citations, scored on retrieval precision
and citation correctness, turns prompt and retrieval changes into measurable ones instead
of matters of taste.

**Streaming tool results into the answer.** Steps stream, and the answer streams, but the
answer does not begin until every step finishes. For a long chain the operator waits on
the slowest tool to read the first sentence. Composing incrementally as evidence arrives
would cut perceived latency substantially.

**A capability boundary on the composer.** Prompt-injection defence today is structural
(delimiters, an explicit trust-boundary instruction) and detective (pattern flags). The
next layer is restricting what the composer is permitted to emit at all — no URLs it was
not given, no credentials-shaped strings, no instructions to the reader — enforced after
generation rather than requested before it.
