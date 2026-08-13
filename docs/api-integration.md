# API integration — Alarm Management API

The contract for the source system the copilot integrates with, derived from the three
Postman collections in [`postman/`](../postman/). Those collections **are** the
specification; this document is the reading of them that
[`services/alarm-simulator/`](../services/alarm-simulator/) implements.

**Acceptance gate:** `make contract` runs all three collections against a running
instance with newman. It must pass before the MCP server is considered integrable.

Current status: **32 chained requests, 15 baseline requests, 0 failures.**

---

## 1. Base configuration

| Property | Value |
|---|---|
| Base URL | `http://localhost:8000` (`http://alarm-simulator:8000` inside compose) |
| Auth | `Authorization: Bearer <token>` on every endpoint except `/health` |
| Default token | `demo-token` — matches the `auth_token` collection variable |
| Content type | `application/json` |

### 1.1 Trace headers

| Header | Direction | Behaviour |
|---|---|---|
| `trace_id` | request and response | Accepted on every endpoint; generated as `trace-<hex>` when absent; always echoed |
| `x-client-id` | request and response | Echoed when supplied |
| `x-metadata-tag` | request and response | Echoed when supplied |

The collections send these on requests 05, 07, 11 and 13. The simulator accepts them
**everywhere**, because a source system that only supports correlation on some
endpoints cannot be correlated end to end.

Analytical responses also carry the triple in a `trace` object in the body, so a
caller can confirm propagation without reading headers.

### 1.2 Error envelope

Every non-2xx response uses one shape:

```json
{ "error": { "code": "NOT_FOUND", "message": "No alarm with id ALM-99999", "trace_id": "trace-abc123" } }
```

| Code | HTTP | Cause |
|---|---:|---|
| `AUTH_FAILED` | 401 | Missing, malformed, or incorrect bearer token |
| `NOT_FOUND` | 404 | Unknown `asset_id`, `alarm_id`, or `calculation_id` |
| `INVALID_INPUT` | 400 / 422 | Failed schema validation or an unknown enum value |
| `INTERNAL_ERROR` | 500 | Unhandled server fault |

A single predictable shape is what lets the MCP server map failures onto stable
`error_code` values the orchestrator can branch on, instead of matching prose.

---

## 2. Endpoint inventory

| # | Method | Path | Auth | Purpose |
|---:|---|---|:---:|---|
| 00 | GET | `/health` | — | Liveness, plus seeded row counts |
| 01 | GET | `/assets/search` | ✔ | Resolve a free-text name to `asset_id` |
| 02 | GET | `/assets/{asset_id}/metadata` | ✔ | Full asset attributes |
| 03 | GET | `/alarms` | ✔ | Paginated, filtered alarm retrieval |
| 04 | GET | `/alarms/{alarm_id}` | ✔ | One alarm |
| 05 | POST | `/alarms/summary` | ✔ | Grouped KPI rollup |
| 06 | POST | `/alarms/trends` | ✔ | Time-bucketed metrics |
| 07 | POST | `/alarms/correlation` | ✔ | Which alarms fire together |
| 08 | POST | `/alarms/flood-analysis` | ✔ | Periods exceeding operator capacity |
| 09 | POST | `/alarms/rationalization-candidates` | ✔ | Alarms that recur or sit stale |
| 10 | POST | `/alarms/priority-score` | ✔ | Weighted priority with factor breakdown |
| 11 | POST | `/recommendations/operator-actions` | ✔ | Ordered response actions |
| 12 | POST | `/calculation-code/generate` | ✔ | Register a KPI calculation |
| 13 | POST | `/calculation-code/execute` | ✔ | Run a registered calculation |
| 14 | GET | `/analytics/kpi-definitions` | ✔ | KPI reference data |

---

## 3. Contract-critical response paths

The collections' own test scripts index these exact paths. Renaming any of them
breaks `make contract`, so they are asserted directly in
`tests/unit/test_simulator_contract.py`.

| Path | Endpoint | Used by |
|---|---|---|
| `results[0].asset_id` | 01 | Baseline 01, CHAIN-01/03/05/08 |
| `data[0].alarm_id` | 03 | Baseline 03, CHAIN-03/05/09 |
| `calculation_id` | 12 | Baseline 12, CHAIN-04/07/10 |
| `flood_windows[0].start` / `.end` | 08 | CHAIN-02 |

Note that 01 returns `results` while 03 returns `data`. The inconsistency is in the
specification, not a mistake here.

---

## 4. Filters visible only in the chaining collection

Reading only the baseline collection produces an API that fails half the chaining
flows. These are easy to miss:

| Endpoint | Extra parameters | First used by |
|---|---|---|
| `/alarms` | `unit`, `site`, `status`, `start_time`, `end_time`, `sort_by`, `sort_order` | CHAIN-02, CHAIN-05, CHAIN-09 |
| `/assets/search` | `unit` | CHAIN-08 |
| `/alarms/summary` | `unit`, `site`, `alarm_types` | CHAIN-02, CHAIN-06, CHAIN-08 |
| `/alarms/rationalization-candidates` | `site`, `unit` | CHAIN-06 |
| `/alarms/trends` | `site` | CHAIN-07 |

---

## 5. Enumerations

Every value observed across the three collections. Anything outside these sets is
rejected with `INVALID_INPUT`.

| Field | Values |
|---|---|
| `severity` | `low`, `medium`, `high`, `critical` |
| `status` | `active`, `acknowledged`, `cleared` |
| `alarm_types` | `process`, `safety`, `device`, `system` |
| `group_by` | `alarm_name`, `asset_id`, `asset_name`, `severity` |
| `kpis` | `alarm_count`, `recurring_rate`, `avg_ack_delay`, `critical_count`, `suppression_candidate_rate` |
| `metrics` (trends) | `alarm_count`, `avg_ack_delay` |
| `bucket` | `hourly`, `daily`, `weekly` |
| `correlation_method` | `cooccurrence` |
| `calculation_type` | `alarm_flood_index`, `critical_alarm_density`, `operator_response_efficiency`, `nuisance_alarm_score` |
| `sort_by` | `start_time`, `severity`, `alarm_name` |
| `sort_order` | `asc`, `desc` |

`severity_threshold` means "this level and above", ordered
`low < medium < high < critical`.

---

## 6. Pagination

`/alarms` only.

| Parameter | Default | Notes |
|---|---:|---|
| `page` | 1 | One-based |
| `page_size` | 50 | **Clamped** to 500, not rejected |

Response carries `page`, `page_size`, `total_count`, and `has_next`.

Clamping rather than rejecting is deliberate: a caller asking for everything gets a
large page and an honest `has_next`, instead of a 422 that would break an otherwise
valid chain mid-flight.

---

## 7. Notable request shapes

### 05 — Summary

```json
{
  "asset_ids": ["AST-0005"],
  "time_range": { "start_time": "2026-05-01T00:00:00Z", "end_time": "2026-07-01T00:00:00Z" },
  "severity": ["high", "critical"],
  "group_by": ["alarm_name"],
  "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay"]
}
```

Scope may be given as `asset_ids`, `unit`, `site`, or any combination. An explicit
scope that matches nothing returns zero results rather than silently widening to the
whole estate.

### 07 — Correlation

```json
{
  "asset_ids": ["AST-0005"],
  "time_range": { "...": "..." },
  "correlation_method": "cooccurrence",
  "lag_window_minutes": 15,
  "severity_threshold": "medium",
  "min_support": 1
}
```

Co-occurrence is computed **within a single asset**. Two alarms on unrelated equipment
firing together is coincidence, not correlation, and counting it would swamp the real
findings. Each pair reports `support`, `confidence`, `lift`, and `mean_lag_seconds`;
`lift` above 1.0 indicates genuine association.

### 12 / 13 — Calculation code

Two steps, because the second is impossible without the identifier the first returns.
This makes the pair the clearest chaining demonstration in the API.

`generate` returns a `calculation_id` and a `generated_code` string. **The code string
is for display only.** Execution runs a reviewed implementation selected by
calculation type — the service never evaluates a supplied string, because a source
system that executes arbitrary code on request is a vulnerability, not a feature.

Filters passed to `execute` override those captured at `generate`, so one calculation
can be re-run against a different scope without regenerating it.

Note that `filters` carries `start_time` and `end_time` **flat**, not nested in a
`time_range` object as the analytical endpoints do. That asymmetry is in the
specification.

---

## 8. Seed data

The simulator generates a deterministic synthetic estate at startup: 30 assets and
3,000 alarms across 120 days, anchored so both the collections' fixed window
(2026-05-01 → 2026-07-01) and "the last 90 days" always contain data.

A fixed seed produces identical `asset_id` and `alarm_id` values on every run, so the
demo, the tests, and the collections all see the same estate.

Several patterns are **engineered rather than random**, because four chaining flows
assert non-empty results and because analytics over uniformly random data finds
nothing — correlation across independent events yields no pairs, and a flood detector
never fires if arrivals are evenly spread:

| Pattern | Location | Required by |
|---|---|---|
| Recurring co-occurring alarm pair | Boiler Feed Pump 101, NorthPlant Unit 2 | CHAIN-01, acceptance scenario |
| Compressor assets | SouthPlant Units 3 and 4 | CHAIN-03 asserts > 0 |
| Motors in Unit 5 | EastRefinery Unit 5 | CHAIN-08 asserts > 0 |
| Active alarms at a site | EastRefinery | CHAIN-09 asserts > 0 |
| Flood bursts | NorthPlant Unit 2 | Flood analysis |
| Stale active alarms | NorthPlant Unit 1 | CHAIN-06 |
| Nuisance repetition | SouthPlant Unit 4 | CHAIN-10 |
| Bimodal acknowledgement delay | SouthPlant | CHAIN-07 |

Each is asserted by `tests/unit/test_simulator_seed.py`, so a regression in the
generator surfaces as a clear statement of what is missing rather than as a confusing
newman failure.

---

## 9. Running the contract check

```bash
uvicorn alarm_simulator.main:app --port 8000    # terminal 1
make contract                                    # terminal 2
```

Requires `npm install -g newman`.
