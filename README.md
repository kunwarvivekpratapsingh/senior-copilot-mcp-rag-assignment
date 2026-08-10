# Multi-MCP Enterprise Operations Copilot

> **Status: in development.** Sections marked _pending_ are completed as the
> corresponding build step lands. See [`docs/hld.md`](docs/hld.md) for the design
> and the implementation plan for sequencing.

A copilot for plant operators. It answers natural-language questions by calling an
Alarm Management API **through purpose-built MCP servers**, retrieving supporting
passages from an operations document corpus, and merging both into a single grounded
answer that carries citations and a visible execution trace.

---

## Selected use case

**Multi-MCP Enterprise Operations Copilot.** The copilot discovers and coordinates
tools across two MCP servers rather than hard-coding integrations, and combines that
structured data with unstructured document evidence in one workflow.

The mandatory acceptance scenario:

> Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last
> 90 days, identify likely contributing factors, retrieve the relevant operating
> procedure, and provide recommended actions with source evidence.

---

## Main capabilities

- Natural-language chat over live alarm data and operations documents
- Runtime tool discovery across two MCP servers — no hard-coded tool list
- Multi-step tool chaining, where one tool's output becomes the next tool's input
- Hybrid document retrieval (BM25 + dense vectors) with inline citations
- One answer combining structured tool results and unstructured document evidence
- Full execution trace: which server, which tool, what arguments, how long, what outcome
- Explicit user confirmation before any write operation
- Graceful degradation on tool failure, timeout, invalid schema, or empty retrieval

---

## Technology stack

| Layer | Choice |
|---|---|
| Backend / orchestration | Python 3.11+, FastAPI, SSE |
| MCP | Official MCP Python SDK (two candidate-built servers) |
| Source system | FastAPI + SQLAlchemy + SQLite simulator, built to the Postman contract |
| LLM | `claude-opus-5` via the `anthropic` SDK, behind a swappable `LLMProvider` protocol |
| Retrieval | Chroma + `rank-bm25` + `sentence-transformers`, fused by reciprocal rank |
| Frontend | React + TypeScript (Vite) |
| Packaging | Docker Compose (6 services), GitHub Actions CI |
| Quality | pytest, ruff (incl. security rules), mypy, newman contract checks |

---

## MCP servers

_Pending — completed in build steps 3 and 6._

Two candidate-built servers:

1. **`alarm-management`** — 14 tools wrapping the Alarm Management API
2. **`github-issues`** — 3 tools for issue search, drafting, and gated creation

The copilot never calls the Alarm Management API directly. The API bearer token lives
inside the MCP server process and is never exposed as a tool argument, so the language
model cannot see or leak it.

Full contracts: [`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md) (generated from
the Pydantic models, so it cannot drift from the code).

## MCP tool list

_Pending — generated in build step 12._

---

## RAG corpus and ingestion

_Pending — completed in build step 5._

Design: [`docs/rag-design.md`](docs/rag-design.md)

---

## Quick start

```bash
git clone <repository-url>
cd senior-copilot-mcp-rag-assignment
cp .env.example .env       # then set ANTHROPIC_API_KEY
docker compose up --build
```

The stack runs fully offline apart from the LLM calls. Set `LLM_PROVIDER=rule_based`
in `.env` to run with no API key at all, using the deterministic planner and composer.

---

## Configuration

All configuration is by environment variable. [`.env.example`](.env.example) documents
every key with a safe placeholder value; no secret is ever committed.

Full reference with types, defaults, and consuming service: `docs/lld.md` §9.

---

## Build and run

`make` is canonical and is what CI uses. On Windows without `make`, `tasks.ps1`
exposes the same target names.

| Task | make | PowerShell |
|---|---|---|
| Install (editable, with dev tools) | `make install` | `.\tasks.ps1 install` |
| Lint | `make lint` | `.\tasks.ps1 lint` |
| Type-check | `make typecheck` | `.\tasks.ps1 typecheck` |
| Start the stack | `make up` | `.\tasks.ps1 up` |
| Stop the stack | `make down` | `.\tasks.ps1 down` |
| Build the RAG index | `make ingest` | `.\tasks.ps1 ingest` |

Run `make help` (or `.\tasks.ps1 help`) for the full list.

### Running an MCP server on its own

_Pending — completed in build step 3._

---

## Tests

| Task | make | PowerShell |
|---|---|---|
| Everything except the stack-dependent tests | `make test` | `.\tasks.ps1 test` |
| Unit only | `make test-unit` | `.\tasks.ps1 test-unit` |
| Integration | `make test-integration` | `.\tasks.ps1 test-integration` |
| End-to-end (needs `make up` first) | `make test-e2e` | `.\tasks.ps1 test-e2e` |
| Coverage report | `make coverage` | `.\tasks.ps1 coverage` |
| API contract vs Postman | `make contract` | `.\tasks.ps1 contract` |

`make contract` requires newman: `npm install -g newman`.

---

## Sample interactions

_Pending — completed in build step 12._

---

## Architecture summary

Six services. The GUI talks to a FastAPI orchestrator over REST and SSE. The
orchestrator plans a sequence of tool calls against a registry it discovered at
runtime from two MCP servers, resolves each step's arguments (including values
produced by earlier steps), retrieves supporting document passages, and composes one
cited answer. Only the MCP servers hold credentials for the systems behind them.

- High-level design, ADRs, and diagrams: [`docs/hld.md`](docs/hld.md)
- Module specs, schemas, algorithms, state machines: [`docs/lld.md`](docs/lld.md)
- Request-flow walkthrough: [`docs/architecture.md`](docs/architecture.md)

### Repository layout

Two documented deviations from the structure in the submission guidelines §3:

- **`services/alarm-simulator/`** — the brief separately mandates a candidate-built
  backend, which is not one of the pre-named folders. Keeping the simulator (the system
  under integration) separate from `connectors/` (the client that reaches it) is a
  cleaner separation than folding both together.
- **`docs/hld.md` and `docs/lld.md`** — added alongside the required
  `docs/architecture.md`, which remains the entry point.

The guidelines permit equivalent structures when clearly documented. Because the
mandated directory names are hyphenated and therefore not valid Python package names,
each holds a correctly-named Python package (`mcp-servers/alarm-management/alarm_mcp/`),
mapped to a top-level import in `pyproject.toml`.

---

## Assumptions

_Pending — completed in build step 12._

## Known limitations

See [`docs/known-limitations.md`](docs/known-limitations.md). _Pending._

## Demo video

_Pending — recorded in build step 12._

---

## License

MIT — see [LICENSE](LICENSE).
