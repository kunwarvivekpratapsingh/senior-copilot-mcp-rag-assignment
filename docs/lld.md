# Low-Level Design

**Multi-MCP Enterprise Operations Copilot**

Companion to [`hld.md`](hld.md). Where the HLD says *what the components are and why*,
this document says *exactly what they contain*: schemas, signatures, algorithms, state
machines, and error mappings.

## How this document is written

Each section is authored **immediately before the component it describes is built**, and
reconciled against the code in the final documentation pass. An LLD written in full
before its dependencies exist is fiction; one written afterwards is a transcript. This
sits between the two.

| § | Contents | Written during | Status |
|---|---|---|---|
| 1 | Data model | Step 2 — simulator | Pending |
| 2 | API contracts | Steps 2, 8 | Pending |
| 3 | MCP tool contracts | Steps 3, 6 | Pending |
| 4 | Module specifications | Steps 3–9 | Pending |
| 5 | Algorithms | Steps 2, 5, 7 | Pending |
| 6 | Sequence diagrams | Step 7 | Pending |
| 7 | State machines | Steps 4, 6, 7 | Pending |
| 8 | Error taxonomy | Step 3 | Pending |
| 9 | Configuration reference | Step 8 | Pending |
| 10 | Test matrix | Step 10 | Pending |

---

## 1. Data model

- **1.1** Simulator entity-relationship diagram
- **1.2** Table definitions — column, type, nullability, default, constraint, index, and
  the meaning of every field
- **1.3** Identifier schemes (`AST-nnnn`, `ALM-nnnnn`, `CALC-nnnn`)
- **1.4** Retrieval index — Chroma collection schema and the chunk metadata record
- **1.5** Trace and conversation store

_Pending — Step 2._

---

## 2. API contracts

- **2.1** Alarm Management API — all 15 endpoints: method, path, request schema,
  response schema, status codes, error codes, auth, trace-header behaviour, pagination
- **2.2** Copilot backend — all 6 endpoints, same treatment
- **2.3** SSE event envelope — `step.started`, `step.succeeded`, `step.failed`,
  `retrieval.completed`, `answer.delta`, `answer.completed`, `confirmation.required`

_Pending — Steps 2 and 8._

---

## 3. MCP tool contracts

All 17 tools, each documented with the ten fields the submission guidelines mandate:
name, purpose, input schema, output schema, authentication behaviour, underlying
source-system operation, error behaviour, timeout behaviour, example invocation, example
response.

This section is the source of truth for the generated
[`mcp-tool-catalog.md`](mcp-tool-catalog.md).

_Pending — Steps 3 and 6._

---

## 4. Module specifications

Public classes, method signatures with types, invariants, async model, and dependency
direction.

- **4.1** `connectors/alarm_api`
- **4.2** `mcp-servers/alarm-management`
- **4.3** `apps/backend/copilot_backend/mcp_client`
- **4.4** `apps/backend/copilot_backend/llm`
- **4.5** `apps/backend/copilot_backend/orchestrator`
- **4.6** `rag/ingestion`
- **4.7** `apps/frontend` — component tree and props contracts

_Pending — Steps 3–9._

---

## 5. Algorithms

Pseudocode and complexity for each.

- **5.1** Co-occurrence correlation — support, confidence, lift within the lag window
- **5.2** Rolling-window flood detection
- **5.3** Header-aware chunking
- **5.4** Reciprocal rank fusion for hybrid retrieval
- **5.5** Citation construction and low-confidence thresholding
- **5.6** Placeholder resolution grammar — `$<stepId>.output.<path>`, array indexing, and
  the behaviour when a path does not resolve
- **5.7** Priority scoring and the KPI formulas
- **5.8** Deterministic seed-data generation

_Pending — Steps 2, 5, 7._

---

## 6. Sequence diagrams

Happy path; chained tool call with placeholder substitution; retrieval inside the same
workflow; tool timeout with retry then degraded answer; write-approval round trip;
ingestion pipeline; startup tool discovery.

_Pending — Step 7._

---

## 7. State machines

- **7.1** Step lifecycle — `pending → resolving → validating → invoking → retrying →
  succeeded | failed | skipped`
- **7.2** Conversation and session
- **7.3** Write-approval gate

_Pending — Steps 4, 6, 7._

---

## 8. Error taxonomy

One table mapping source condition → typed exception → MCP `error_code` → HTTP status →
user-visible message → GUI treatment → whether it is retried.

_Pending — Step 3._

---

## 9. Configuration reference

Every environment variable: name, type, default, required, consuming service, whether it
is a secret, and the effect when it is absent. Cross-checked against `.env.example`.

_Pending — Step 8._

---

## 10. Test matrix

Test ID → category → target module → precondition → assertion → the `FR-xx` it covers.
Feeds the traceability matrix in [`hld.md`](hld.md#12-traceability-matrix).

_Pending — Step 10._
