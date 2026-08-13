# Demo walkthrough

The recorded demo runs ≤10 minutes and follows the script below. Both halves matter: the
happy path shows the system working, and the failure path shows it failing honestly,
which is the harder property to demonstrate and the one the submission guidelines name
repeatedly.

> **Recording:** `docs/demo.mp4` (or the link in the submission form).

## Setup

```bash
cp .env.example .env
docker compose up --build
```

Wait for `backend` to report healthy, then open http://localhost:5173. Everything below
uses the default configuration — no API key, deterministic provider — unless the segment
says otherwise.

## 1 · Tool discovery (≈1 min)

Open the **Tools** tab before asking anything.

- Both servers are connected; the header pills show `alarm-management · 14 tools` and
  `github-issues · 3 tools`.
- Expand `search_assets` and `get_alarm_correlation` to show the JSON input and output
  schemas as discovered at runtime.

Say what this proves: nothing about alarms is compiled into the copilot. The registry is
built from `list_tools()` at startup, and the planner, the GUI, and the argument
validator all read the same cache.

## 2 · The acceptance scenario (≈3 min)

Paste the scenario question:

> Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90
> days, identify likely contributing factors, retrieve the relevant operating procedure,
> and provide recommended actions with source evidence.

Point out, in the **Execution** tab as it fills in live:

1. `s1 search_assets` resolves the name to an asset id.
2. `s2 get_alarm_summary` — expand it and show `asset_ids` contains the id `s1` returned.
   That substitution is the chaining requirement, visible on the wire.
3. `s3 get_alarm_correlation` finds the co-occurring pair.
4. `s4 get_rationalization_candidates` confirms which alarms warrant re-tuning.
5. `r1` retrieval — expand it and show `asset: "Boiler Feed Pump 101"`, a filter **no one
   typed**. This is the join that makes MCP and RAG one workflow rather than two
   features.

Then the answer: correlation findings carrying `[tool: …]` markers, procedure steps
carrying `[source: OP-BFP-101#…]`. Click a citation chip — it jumps to the **Evidence**
tab, where the passage, its section, and its score are shown.

## 3 · The write gate (≈1 min)

Ask:

> Find recurring alarms for Boiler Feed Pump 101 and raise a GitHub issue for them.

The run stops at `create_issue` with a confirmation dialog showing the exact arguments.

- **Cancel** — nothing is written.
- Ask again and **Approve** — the step runs and returns an issue number.

Say what this proves: the gate is in the tool contract, not the dialog. `create_issue`
raises `CONFIRMATION_REQUIRED` unless `confirmed: true`, so any other caller — including
the model, including anything bypassing the UI — is refused identically.

## 4 · Honest failure: no supporting document (≈1 min)

Ask something the corpus cannot answer:

> What is the quarterly maintenance budget for the retail division?

Retrieval reports low confidence, the answer says plainly that no relevant procedure was
found, and no recommendation is dressed up as grounded. A confident answer built on no
evidence is the worst thing this system could produce, so the honest failure is a
designed path.

## 5 · Honest failure: the source system goes down (≈2 min)

With the browser open:

```bash
docker compose stop alarm-simulator
```

Re-ask the acceptance question.

- The MCP server retries on connection failure, then maps the failure to a stable error
  code.
- Failed steps are red in the timeline with their error code; the retrieval step still
  **succeeds**, because it does not depend on them.
- The answer contains a "What could not be determined" section rather than silently
  omitting the missing findings.

Then:

```bash
docker compose start alarm-simulator
```

Re-ask and show full recovery.

Optionally show `docker compose logs backend | grep tool_failed` — one structured JSON
record per failure carrying `mcp_server`, `mcp_tool`, `error_code`, `duration_ms`,
`retry_count`, and `trace_id`, the same fields the timeline renders. Observability and
GUI traceability are the same feature, from one model.

## 6 · Prompt injection (≈1 min)

Ask:

> What does the vendor service bulletin say about seal flush?

`VENDOR-2026-04` is retrieved and the evidence panel flags it: *this document contains
text resembling an embedded instruction*. The document's payload asks for
`ALARM_API_TOKEN`. The answer does not comply, and the token is not reachable in the
first place — it lives in the MCP server's configuration and is never a tool argument, a
tool output, or a log field.

## 7 · The LLM path (≈1 min, optional)

Set `LLM_PROVIDER=anthropic` with a key in `.env`, `docker compose up -d backend`, and
re-ask the acceptance question. Same plan, same tools, same citations — narrative prose
instead of assembled sections. The footer changes from `rule_based` to
`anthropic:claude-opus-5`, and the trace records which provider planned the request.

The point of showing both: the provider is a protocol with two real implementations, so
the abstraction is demonstrated rather than asserted, and the system degrades to a
working state when no key is present.
