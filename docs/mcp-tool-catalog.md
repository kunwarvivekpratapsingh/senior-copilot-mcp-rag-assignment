# MCP Tool Catalog

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python scripts/gen_tool_catalog.py
     CI runs `--check`, so an edited schema with a stale catalog fails. -->

17 tools across 2 MCP servers (alarm-management: 14, github-issues: 3).

Every entry below carries the ten fields the submission guidelines require.
Example responses are real output from the seeded simulator, captured when
this file was generated.

## Behaviour common to every tool

| Property | Behaviour |
| --- | --- |
| Authentication | The bearer token is held in the MCP server's configuration and injected by the connector. **No tool accepts a credential as an argument**, so a model driving these tools cannot read, leak, or be persuaded to reveal it. |
| Timeout | 5s per upstream request (`ALARM_API_TIMEOUT_SECONDS`); the MCP client applies its own 8s ceiling (`MCP_TOOL_TIMEOUT_SECONDS`). |
| Retry | Up to 2 retries with exponential backoff, on 5xx and connection errors only. A 4xx is never retried — the request was wrong and will stay wrong. |
| Errors | Returned as `[CODE] message` with a stable code: `NOT_FOUND`, `INVALID_INPUT`, `AUTH_FAILED`, `UPSTREAM_5XX`, `TIMEOUT`, `CONFIRMATION_REQUIRED`. The orchestrator branches on the code and shows the message. |
| Tracing | `trace_id` is accepted, generated when absent, forwarded upstream, and returned in `meta.trace_id`. |

## Server: `alarm-management`

### `execute_calculation`

**Purpose.** Run a prepared calculation and return its value with a supporting table.

Step two of two — requires a calculation_id from generate_calculation.

    Filters supplied here override those captured at generation, so the same
    calculation can be re-run against a different unit or period without preparing
    it again. The response includes a plain-language interpretation alongside the
    number.

**Underlying operation.** `POST /calculations/execute`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "calculation_id": {
      "description": "The id returned by generate_calculation",
      "title": "Calculation Id",
      "type": "string"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "required": [
    "calculation_id"
  ],
  "title": "execute_calculationArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "calculation_id": {
      "title": "Calculation Id",
      "type": "string"
    },
    "calculation_type": {
      "title": "Calculation Type",
      "type": "string"
    },
    "columns": {
      "items": {
        "type": "string"
      },
      "title": "Columns",
      "type": "array"
    },
    "interpretation": {
      "title": "Interpretation",
      "type": "string"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "rows": {
      "items": {
        "items": {},
        "type": "array"
      },
      "title": "Rows",
      "type": "array"
    },
    "unit": {
      "title": "Unit",
      "type": "string"
    },
    "value": {
      "title": "Value",
      "type": "number"
    }
  },
  "required": [
    "calculation_id",
    "calculation_type",
    "value",
    "unit",
    "columns",
    "rows",
    "interpretation",
    "meta"
  ],
  "title": "ExecuteCalculationOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "calculation_id": "CALC-24438d18bf85"
  },
  "tool": "execute_calculation"
}
```

**Example response.**

```json
{
  "calculation_id": "CALC-24438d18bf85",
  "calculation_type": "operator_response_efficiency",
  "columns": [
    "metric",
    "value"
  ],
  "interpretation": "26.8% of acknowledged alarms were answered within 300 seconds.",
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-d13bbe91c30e"
  },
  "rows": [
    [
      "acknowledged_alarms",
      792
    ],
    [
      "within_threshold",
      212
    ],
    [
      "median_delay_seconds",
      794.0
    ]
  ],
  "unit": "ratio",
  "value": 0.2677
}
```

### `generate_calculation`

**Purpose.** Prepare a KPI calculation and return its identifier.

Step one of two. This registers the calculation and returns a calculation_id;
    it does not compute anything. Pass that id to execute_calculation to get the
    value. There is no way to run a calculation without calling this first.

    Types: alarm_flood_index (share of alarms arriving during floods),
    critical_alarm_density (critical alarms per asset per day),
    operator_response_efficiency (share acknowledged within five minutes),
    nuisance_alarm_score (share coming from excessively repeating alarm names).

**Underlying operation.** `POST /calculations/generate`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "calculation_type": {
      "description": "Which KPI calculation to prepare",
      "enum": [
        "alarm_flood_index",
        "critical_alarm_density",
        "operator_response_efficiency",
        "nuisance_alarm_score"
      ],
      "title": "Calculation Type",
      "type": "string"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "required": [
    "calculation_type"
  ],
  "title": "generate_calculationArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "calculation_id": {
      "description": "Pass this to execute_calculation. The value does not exist until this tool has run, which is what makes the pair a genuine chain.",
      "title": "Calculation Id",
      "type": "string"
    },
    "calculation_type": {
      "title": "Calculation Type",
      "type": "string"
    },
    "generated_code": {
      "description": "For display only; never executed",
      "title": "Generated Code",
      "type": "string"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    }
  },
  "required": [
    "calculation_id",
    "calculation_type",
    "generated_code",
    "meta"
  ],
  "title": "GenerateCalculationOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "calculation_type": "operator_response_efficiency",
    "end_time": "2026-08-13T13:59:48.916104+00:00",
    "site": "SouthPlant",
    "start_time": "2026-05-15T13:59:48.916104+00:00"
  },
  "tool": "generate_calculation"
}
```

**Example response.**

```json
{
  "calculation_id": "CALC-ff0d9655e86e",
  "calculation_type": "operator_response_efficiency",
  "generated_code": "def operator_response_efficiency(alarms, prompt_seconds=300):\n    \"\"\"Share of acknowledged alarms answered within the prompt threshold.\"\"\"\n    acked = [a for a in alarms if a.ack_delay_seconds is not None]\n    prompt = [a for a in acked if a.ack_delay_seconds <= prompt_seconds]\n    return len(prompt) / len(acked) if acked else 0.0",
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-7bc34e9d88b6"
  }
}
```

### `get_alarm_by_id`

**Purpose.** Retrieve the full detail of one alarm by its id.

Returns the process value that triggered it and the setpoint it crossed, the
    acknowledgement time and delay, and the current status. Use after get_alarms has
    identified an alarm of interest, or when another tool has returned an alarm_id
    you need the full record for.

**Underlying operation.** `GET /alarms/{alarm_id}`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "alarm_id": {
      "description": "Alarm id, e.g. ALM-00069",
      "title": "Alarm Id",
      "type": "string"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    }
  },
  "required": [
    "alarm_id"
  ],
  "title": "get_alarm_by_idArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "AlarmRecord": {
      "properties": {
        "ack_delay_seconds": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Ack Delay Seconds"
        },
        "ack_time": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Ack Time"
        },
        "alarm_id": {
          "title": "Alarm Id",
          "type": "string"
        },
        "alarm_name": {
          "title": "Alarm Name",
          "type": "string"
        },
        "alarm_type": {
          "title": "Alarm Type",
          "type": "string"
        },
        "asset_id": {
          "title": "Asset Id",
          "type": "string"
        },
        "asset_name": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Asset Name"
        },
        "end_time": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "End Time"
        },
        "operator_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Operator Id"
        },
        "setpoint": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Setpoint"
        },
        "severity": {
          "title": "Severity",
          "type": "string"
        },
        "start_time": {
          "title": "Start Time",
          "type": "string"
        },
        "status": {
          "title": "Status",
          "type": "string"
        },
        "unit_of_measure": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Unit Of Measure"
        },
        "value": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Value"
        }
      },
      "required": [
        "alarm_id",
        "asset_id",
        "alarm_name",
        "alarm_type",
        "severity",
        "status",
        "start_time"
      ],
      "title": "AlarmRecord",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "alarm": {
      "$ref": "#/$defs/AlarmRecord"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    }
  },
  "required": [
    "alarm",
    "meta"
  ],
  "title": "GetAlarmOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "alarm_id": "ALM-00069"
  },
  "tool": "get_alarm_by_id"
}
```

**Example response.**

```json
{
  "alarm": {
    "ack_delay_seconds": null,
    "ack_time": null,
    "alarm_id": "ALM-00069",
    "alarm_name": "Discharge Pressure Low",
    "alarm_type": "process",
    "asset_id": "AST-0005",
    "asset_name": "Boiler Feed Pump 101",
    "end_time": null,
    "operator_id": null,
    "setpoint": 98.8,
    "severity": "high",
    "start_time": "2026-08-13T10:59:48.157382",
    "status": "active",
    "unit_of_measure": "barg",
    "value": 127.9
  },
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-573a7af29da5"
  }
}
```

### `get_alarm_correlation`

**Purpose.** Find which alarms tend to fire together, and how strongly.

The primary tool for 'what is causing this' and 'what else happens at the same
    time'. Co-occurrence is measured within a single asset, so a reported pair is a
    real relationship on that equipment rather than two unrelated events coinciding.

    Read `lift` before `support`: support counts how often the pair occurred, but
    lift says whether that is more than chance. Lift near 1.0 means no real
    association however large the support; above 1.0 indicates a genuine link.

**Underlying operation.** `POST /alarms/correlation`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "asset_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Asset ids from search_assets. Omit to scope by unit or site instead.",
      "title": "Asset Ids"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "lag_window_minutes": {
      "default": 15,
      "description": "How close in time two alarms must be to count",
      "maximum": 1440,
      "minimum": 1,
      "title": "Lag Window Minutes",
      "type": "integer"
    },
    "min_support": {
      "default": 1,
      "description": "Minimum co-occurrences before a pair is reported",
      "minimum": 1,
      "title": "Min Support",
      "type": "integer"
    },
    "severity_threshold": {
      "default": "medium",
      "description": "Consider only this severity and above",
      "enum": [
        "low",
        "medium",
        "high",
        "critical"
      ],
      "title": "Severity Threshold",
      "type": "string"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "title": "get_alarm_correlationArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "CorrelationPair": {
      "properties": {
        "alarm_a": {
          "title": "Alarm A",
          "type": "string"
        },
        "alarm_b": {
          "title": "Alarm B",
          "type": "string"
        },
        "confidence": {
          "description": "Given alarm_a fired, how often alarm_b followed",
          "title": "Confidence",
          "type": "number"
        },
        "lift": {
          "description": "Association strength versus chance. Above 1.0 indicates a real relationship; near 1.0 means the pair is no more related than coincidence.",
          "title": "Lift",
          "type": "number"
        },
        "mean_lag_seconds": {
          "title": "Mean Lag Seconds",
          "type": "number"
        },
        "support": {
          "description": "Times the pair co-occurred inside the lag window",
          "title": "Support",
          "type": "integer"
        }
      },
      "required": [
        "alarm_a",
        "alarm_b",
        "support",
        "confidence",
        "lift",
        "mean_lag_seconds"
      ],
      "title": "CorrelationPair",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "correlation_method": {
      "title": "Correlation Method",
      "type": "string"
    },
    "lag_window_minutes": {
      "title": "Lag Window Minutes",
      "type": "integer"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "pairs": {
      "items": {
        "$ref": "#/$defs/CorrelationPair"
      },
      "title": "Pairs",
      "type": "array"
    }
  },
  "required": [
    "correlation_method",
    "lag_window_minutes",
    "pairs",
    "meta"
  ],
  "title": "AlarmCorrelationOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "asset_ids": [
      "AST-0005"
    ],
    "end_time": "2026-08-13T13:59:48.916104+00:00",
    "min_support": 3,
    "start_time": "2026-05-15T13:59:48.916104+00:00"
  },
  "tool": "get_alarm_correlation"
}
```

**Example response.**

```json
{
  "correlation_method": "cooccurrence",
  "lag_window_minutes": 15,
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-75f88b0a671d"
  },
  "pairs": [
    {
      "alarm_a": "Discharge Pressure Low",
      "alarm_b": "Suction Strainer DP High",
      "confidence": 0.7209,
      "lift": 2.2922,
      "mean_lag_seconds": 392.6,
      "support": 31
    },
    {
      "alarm_a": "Motor Current High",
      "alarm_b": "Vibration High",
      "confidence": 0.8,
      "lift": 8.2667,
      "mean_lag_seconds": 220.2,
      "support": 4
    },
    {
      "alarm_a": "Motor Current High",
      "alarm_b": "Suction Strainer DP High",
      "confidence": 0.6,
      "lift": 1.9077,
      "mean_lag_seconds": 289.0,
      "support": 3
    },
    {
      "alarm_a": "Vibration High",
      "alarm_b": "Discharge Pressure Low",
      "confidence": 0.25,
      "lift": 0.7209,
      "mean_lag_seconds": 110.3,
      "support": 3
    }
  ]
}
```

### `get_alarm_summary`

**Purpose.** Aggregate alarms into groups and compute KPIs for each.

The main tool for 'how often', 'how many', and 'which alarm dominates'. Grouping
    by alarm_name answers what recurs; grouping by asset_id answers which equipment
    is worst.

    KPIs available: alarm_count, critical_count, avg_ack_delay (mean seconds to
    acknowledge), recurring_rate (share of alarms that repeat a name already seen,
    where values near 1.0 mean a handful of alarms firing over and over), and
    suppression_candidate_rate.

**Underlying operation.** `POST /alarms/summary`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "alarm_types": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "e.g. ['safety','device']",
      "title": "Alarm Types"
    },
    "asset_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Asset ids from search_assets. Omit to scope by unit or site instead.",
      "title": "Asset Ids"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "group_by": {
      "default": [
        "alarm_name"
      ],
      "description": "Dimensions to group by",
      "items": {
        "enum": [
          "alarm_name",
          "asset_id",
          "asset_name",
          "severity"
        ],
        "type": "string"
      },
      "title": "Group By",
      "type": "array"
    },
    "kpis": {
      "default": [
        "alarm_count"
      ],
      "description": "KPIs to compute per group",
      "items": {
        "enum": [
          "alarm_count",
          "recurring_rate",
          "avg_ack_delay",
          "critical_count",
          "suppression_candidate_rate"
        ],
        "type": "string"
      },
      "title": "Kpis",
      "type": "array"
    },
    "severity": {
      "anyOf": [
        {
          "items": {
            "enum": [
              "low",
              "medium",
              "high",
              "critical"
            ],
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Restrict to these severities",
      "title": "Severity"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "title": "get_alarm_summaryArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "SummaryGroup": {
      "properties": {
        "group": {
          "additionalProperties": {
            "type": "string"
          },
          "title": "Group",
          "type": "object"
        },
        "kpis": {
          "additionalProperties": {
            "type": "number"
          },
          "title": "Kpis",
          "type": "object"
        }
      },
      "required": [
        "group",
        "kpis"
      ],
      "title": "SummaryGroup",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "groups": {
      "items": {
        "$ref": "#/$defs/SummaryGroup"
      },
      "title": "Groups",
      "type": "array"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "total_alarms": {
      "title": "Total Alarms",
      "type": "integer"
    }
  },
  "required": [
    "total_alarms",
    "groups",
    "meta"
  ],
  "title": "AlarmSummaryOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "asset_ids": [
      "AST-0005"
    ],
    "end_time": "2026-08-13T13:59:48.916104+00:00",
    "group_by": [
      "alarm_name"
    ],
    "kpis": [
      "alarm_count",
      "recurring_rate"
    ],
    "severity": [
      "high",
      "critical"
    ],
    "start_time": "2026-05-15T13:59:48.916104+00:00"
  },
  "tool": "get_alarm_summary"
}
```

**Example response.**

```json
{
  "groups": [
    {
      "group": {
        "alarm_name": "Discharge Pressure Low"
      },
      "kpis": {
        "alarm_count": 39.0,
        "recurring_rate": 0.9744
      }
    },
    {
      "group": {
        "alarm_name": "Suction Strainer DP High"
      },
      "kpis": {
        "alarm_count": 35.0,
        "recurring_rate": 0.9714
      }
    },
    {
      "group": {
        "alarm_name": "Bearing Temperature High"
      },
      "kpis": {
        "alarm_count": 8.0,
        "recurring_rate": 0.875
      }
    },
    {
      "group": {
        "alarm_name": "Seal Leak Detected"
      },
      "kpis": {
        "alarm_count": 6.0,
        "recurring_rate": 0.8333
      }
    },
    {
      "group": {
        "alarm_name": "Vibration High"
      },
      "kpis": {
        "alarm_count": 4.0,
        "recurring_rate": 0.75
      }
    },
    {
      "group": {
        "alarm_name": "Motor Current High"
      },
      "kpis": {
        "alarm_count": 2.0,
        "recurring_rate": 0.5
      }
    }
  ],
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-2aa863c2cfca"
  },
  "total_alarms": 94
}
```

### `get_alarm_trends`

**Purpose.** Alarm metrics bucketed over time.

Use when the question is about direction — is this getting worse, did it change
    after an intervention, when did it start. For a single total, use
    get_alarm_summary instead.

**Underlying operation.** `POST /alarms/trends`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "asset_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Asset ids from search_assets. Omit to scope by unit or site instead.",
      "title": "Asset Ids"
    },
    "bucket": {
      "default": "daily",
      "enum": [
        "hourly",
        "daily",
        "weekly"
      ],
      "title": "Bucket",
      "type": "string"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "metrics": {
      "default": [
        "alarm_count"
      ],
      "description": "Metrics per bucket",
      "items": {
        "enum": [
          "alarm_count",
          "avg_ack_delay"
        ],
        "type": "string"
      },
      "title": "Metrics",
      "type": "array"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "title": "get_alarm_trendsArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    },
    "TrendPoint": {
      "properties": {
        "bucket_start": {
          "title": "Bucket Start",
          "type": "string"
        },
        "metrics": {
          "additionalProperties": {
            "type": "number"
          },
          "title": "Metrics",
          "type": "object"
        }
      },
      "required": [
        "bucket_start",
        "metrics"
      ],
      "title": "TrendPoint",
      "type": "object"
    }
  },
  "properties": {
    "bucket": {
      "title": "Bucket",
      "type": "string"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "points": {
      "items": {
        "$ref": "#/$defs/TrendPoint"
      },
      "title": "Points",
      "type": "array"
    }
  },
  "required": [
    "bucket",
    "points",
    "meta"
  ],
  "title": "AlarmTrendsOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "asset_ids": [
      "AST-0005"
    ],
    "bucket": "daily",
    "end_time": "2026-08-13T13:59:48.916104+00:00",
    "metrics": [
      "alarm_count"
    ],
    "start_time": "2026-05-15T13:59:48.916104+00:00"
  },
  "tool": "get_alarm_trends"
}
```

**Example response.**

```json
{
  "bucket": "daily",
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-8558dbbe8cf1"
  },
  "points": [
    {
      "bucket_start": "2026-05-16T00:00:00Z",
      "metrics": {
        "alarm_count": 1.0
      }
    },
    {
      "bucket_start": "2026-05-17T00:00:00Z",
      "metrics": {
        "alarm_count": 3.0
      }
    },
    {
      "bucket_start": "2026-05-18T00:00:00Z",
      "metrics": {
        "alarm_count": 1.0
      }
    },
    {
      "bucket_start": "2026-05-20T00:00:00Z",
      "metrics": {
        "alarm_count": 3.0
      }
    },
    {
      "bucket_start": "2026-05-21T00:00:00Z",
      "metrics": {
        "alarm_count": 2.0
      }
    },
    {
      "bucket_start": "2026-05-22T00:00:00Z",
      "metrics": {
        "alarm_count": 2.0
      }
    },
    {
      "bucket_start": "2026-05-23T00:00:00Z",
      "metrics": {
        "alarm_count": 1.0
      }
    },
    {
      "bucket_start": "2026-05-26T00:00:00Z",
      "metrics": {
        "alarm_count": 4.0
      }
    },
    {
      "bucket_start": "2026-05-27T00:00:00Z",
      "metrics": {
        "alarm_count": 1.0
      }
    },
    {
      "bucket_start": "2026-05-28T00:00:00Z",
      "metrics": {
        "alarm_count": 4.0
      }
    },
    {
      "bucket_start": "2026-05-30T00:00:00Z",
      "metrics": {
        "alarm_count": 1.0
      }
    },
    {
      "bucket_start":
  … truncated for the catalog
```

### `get_alarms`

**Purpose.** List individual alarms with filtering, sorting, and pagination.

Use when the question is about specific alarm occurrences — 'what is active right
    now', 'the most recent alarm on this pump'. For counts, rates, or patterns use
    get_alarm_summary instead; it aggregates server-side rather than making you page
    through rows.

    The response reports total_count and has_next, so check those before concluding
    a list is complete.

**Underlying operation.** `GET /alarms`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "asset_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Restrict to one asset",
      "title": "Asset Id"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "page": {
      "default": 1,
      "description": "One-based page number",
      "minimum": 1,
      "title": "Page",
      "type": "integer"
    },
    "page_size": {
      "default": 50,
      "description": "Rows per page, capped at 500",
      "minimum": 1,
      "title": "Page Size",
      "type": "integer"
    },
    "severity": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "One of: low, medium, high, critical",
      "title": "Severity"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "sort_by": {
      "default": "start_time",
      "enum": [
        "start_time",
        "severity",
        "alarm_name"
      ],
      "title": "Sort By",
      "type": "string"
    },
    "sort_order": {
      "default": "desc",
      "enum": [
        "asc",
        "desc"
      ],
      "title": "Sort Order",
      "type": "string"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "status": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "One of: active, acknowledged, cleared",
      "title": "Status"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "title": "get_alarmsArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "AlarmRecord": {
      "properties": {
        "ack_delay_seconds": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Ack Delay Seconds"
        },
        "ack_time": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Ack Time"
        },
        "alarm_id": {
          "title": "Alarm Id",
          "type": "string"
        },
        "alarm_name": {
          "title": "Alarm Name",
          "type": "string"
        },
        "alarm_type": {
          "title": "Alarm Type",
          "type": "string"
        },
        "asset_id": {
          "title": "Asset Id",
          "type": "string"
        },
        "asset_name": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Asset Name"
        },
        "end_time": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "End Time"
        },
        "operator_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Operator Id"
        },
        "setpoint": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Setpoint"
        },
        "severity": {
          "title": "Severity",
          "type": "string"
        },
        "start_time": {
          "title": "Start Time",
          "type": "string"
        },
        "status": {
          "title": "Status",
          "type": "string"
        },
        "unit_of_measure": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Unit Of Measure"
        },
        "value": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Value"
        }
      },
      "required": [
        "alarm_id",
        "asset_id",
        "alarm_name",
        "alarm_type",
        "severity",
        "status",
        "start_time"
      ],
      "title": "AlarmRecord",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "data": {
      "items": {
        "$ref": "#/$defs/AlarmRecord"
      },
      "title": "Data",
      "type": "array"
    },
    "has_next": {
      "title": "Has Next",
      "type": "boolean"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "page": {
      "title": "Page",
      "type": "integer"
    },
    "page_size": {
      "title": "Page Size",
      "type": "integer"
    },
    "total_count": {
      "title": "Total Count",
      "type": "integer"
    }
  },
  "required": [
    "data",
    "page",
    "page_size",
    "total_count",
    "has_next",
    "meta"
  ],
  "title": "GetAlarmsOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "asset_id": "AST-0005",
    "page_size": 2
  },
  "tool": "get_alarms"
}
```

**Example response.**

```json
{
  "data": [
    {
      "ack_delay_seconds": null,
      "ack_time": null,
      "alarm_id": "ALM-00069",
      "alarm_name": "Discharge Pressure Low",
      "alarm_type": "process",
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "end_time": null,
      "operator_id": null,
      "setpoint": 98.8,
      "severity": "high",
      "start_time": "2026-08-13T10:59:48.157382",
      "status": "active",
      "unit_of_measure": "barg",
      "value": 127.9
    },
    {
      "ack_delay_seconds": 592,
      "ack_time": "2026-08-13T06:55:03.157382",
      "alarm_id": "ALM-01542",
      "alarm_name": "Bearing Temperature High",
      "alarm_type": "process",
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "end_time": "2026-08-13T08:38:11.157382",
      "operator_id": "OP-009",
      "setpoint": 87.8,
      "severity": "high",
      "start_time": "2026-08-13T06:45:11.157382",
      "status": "cleared",
      "unit_of_measure": "degC",
      "value": 139.6
    }
  ],
  "has_next": true,
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-4b6e3bc603b7"
  },
  "page": 1,
  "page_size": 2,
  "total_count": 168
}
```

### `get_asset_metadata`

**Purpose.** Full attributes for one asset, plus its current alarm counts.

Use when the answer depends on what the equipment *is* — its criticality,
    manufacturer, install date, or how long since it was last maintained.

**Underlying operation.** `GET /assets/{asset_id}/metadata`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "asset_id": {
      "description": "Asset id from search_assets, e.g. AST-0005",
      "title": "Asset Id",
      "type": "string"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    }
  },
  "required": [
    "asset_id"
  ],
  "title": "get_asset_metadataArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "active_alarms": {
      "title": "Active Alarms",
      "type": "integer"
    },
    "asset_id": {
      "title": "Asset Id",
      "type": "string"
    },
    "asset_name": {
      "title": "Asset Name",
      "type": "string"
    },
    "asset_type": {
      "title": "Asset Type",
      "type": "string"
    },
    "criticality": {
      "title": "Criticality",
      "type": "string"
    },
    "install_date": {
      "title": "Install Date",
      "type": "string"
    },
    "last_maintenance": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Last Maintenance"
    },
    "manufacturer": {
      "title": "Manufacturer",
      "type": "string"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "model": {
      "title": "Model",
      "type": "string"
    },
    "site": {
      "title": "Site",
      "type": "string"
    },
    "total_alarms": {
      "title": "Total Alarms",
      "type": "integer"
    },
    "unit": {
      "title": "Unit",
      "type": "string"
    }
  },
  "required": [
    "asset_id",
    "asset_name",
    "asset_type",
    "unit",
    "site",
    "criticality",
    "manufacturer",
    "model",
    "install_date",
    "last_maintenance",
    "total_alarms",
    "active_alarms",
    "meta"
  ],
  "title": "AssetMetadataOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "asset_id": "AST-0005"
  },
  "tool": "get_asset_metadata"
}
```

**Example response.**

```json
{
  "active_alarms": 4,
  "asset_id": "AST-0005",
  "asset_name": "Boiler Feed Pump 101",
  "asset_type": "pump",
  "criticality": "high",
  "install_date": "2021-11-30T13:59:48.157382",
  "last_maintenance": "2025-09-24T13:59:48.157382",
  "manufacturer": "Emerson",
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-4c3c809d061d"
  },
  "model": "PUM-4536",
  "site": "NorthPlant",
  "total_alarms": 168,
  "unit": "Unit 2"
}
```

### `get_flood_analysis`

**Purpose.** Find periods where alarms arrived faster than an operator could process them.

Alarm flooding is a recognised failure mode: during a flood the operator cannot
    read, let alone act on, what the console is showing, so genuinely important
    alarms get missed. Each returned window reports its span, how many alarms it
    contained, which assets contributed, and the dominant alarm name.

    Overlapping detections are merged, so one burst produces one window.

**Underlying operation.** `POST /alarms/flood-analysis`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "asset_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Asset ids from search_assets. Omit to scope by unit or site instead.",
      "title": "Asset Ids"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "rolling_window_minutes": {
      "default": 10,
      "description": "Width of the rolling window",
      "maximum": 1440,
      "minimum": 1,
      "title": "Rolling Window Minutes",
      "type": "integer"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "threshold_count": {
      "default": 10,
      "description": "Alarms within the window that constitute a flood",
      "minimum": 1,
      "title": "Threshold Count",
      "type": "integer"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "title": "get_flood_analysisArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "FloodWindow": {
      "properties": {
        "alarm_count": {
          "title": "Alarm Count",
          "type": "integer"
        },
        "contributing_assets": {
          "items": {
            "type": "string"
          },
          "title": "Contributing Assets",
          "type": "array"
        },
        "dominant_alarm_name": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Dominant Alarm Name"
        },
        "end": {
          "title": "End",
          "type": "string"
        },
        "peak_rate_per_minute": {
          "title": "Peak Rate Per Minute",
          "type": "number"
        },
        "start": {
          "title": "Start",
          "type": "string"
        }
      },
      "required": [
        "start",
        "end",
        "alarm_count",
        "peak_rate_per_minute",
        "contributing_assets"
      ],
      "title": "FloodWindow",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "flood_windows": {
      "items": {
        "$ref": "#/$defs/FloodWindow"
      },
      "title": "Flood Windows",
      "type": "array"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "rolling_window_minutes": {
      "title": "Rolling Window Minutes",
      "type": "integer"
    },
    "threshold_count": {
      "title": "Threshold Count",
      "type": "integer"
    }
  },
  "required": [
    "threshold_count",
    "rolling_window_minutes",
    "flood_windows",
    "meta"
  ],
  "title": "FloodAnalysisOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "end_time": "2026-08-13T13:59:48.916104+00:00",
    "rolling_window_minutes": 10,
    "start_time": "2026-05-15T13:59:48.916104+00:00",
    "threshold_count": 10,
    "unit": "Unit 2"
  },
  "tool": "get_flood_analysis"
}
```

**Example response.**

```json
{
  "flood_windows": [
    {
      "alarm_count": 26,
      "contributing_assets": [
        "AST-0005",
        "AST-0006",
        "AST-0007",
        "AST-0008",
        "AST-0009",
        "AST-0010"
      ],
      "dominant_alarm_name": "Motor Current High",
      "end": "2026-07-16T01:06:50.157382Z",
      "peak_rate_per_minute": 4.15,
      "start": "2026-07-16T01:00:34.157382Z"
    },
    {
      "alarm_count": 26,
      "contributing_assets": [
        "AST-0005",
        "AST-0006",
        "AST-0007",
        "AST-0008",
        "AST-0009",
        "AST-0010"
      ],
      "dominant_alarm_name": "Bearing Temperature High",
      "end": "2026-08-03T08:07:43.157382Z",
      "peak_rate_per_minute": 3.37,
      "start": "2026-08-03T08:00:00.157382Z"
    },
    {
      "alarm_count": 18,
      "contributing_assets": [
        "AST-0005",
        "AST-0006",
        "AST-0007",
        "AST-0008",
        "AST-0009",
        "AST-0010"
      ],
      "dominant_alarm_name": "Vibration High",
      "end": "2026-06-28T03:07:38.157382Z",
      "peak_rate_per_minute": 2.43,
      "start": "2026-06-28T03:00:14.157382Z"
    },
    {
      "alarm_count": 17,
      "contributing_assets": [
        "AST-0005",
        "AST-0006",
        "AST-0007",
        "AST-0009",
        "AST-0010"
      ],
      "dominant_alarm_name": "Vibration High",
      "end": "2026-06-10T06:07:26.15738
  … truncated for the catalog
```

### `get_kpi_definitions`

**Purpose.** Definitions and formulas for every KPI the summary tool can compute.

Use when a question asks what a metric means, or when an answer should state how
    a figure was derived. Sourcing the formula from the system avoids restating a
    definition that could drift from the implementation.

**Underlying operation.** `GET /analytics/kpi-definitions`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    }
  },
  "title": "get_kpi_definitionsArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "KpiDefinition": {
      "properties": {
        "description": {
          "title": "Description",
          "type": "string"
        },
        "display_name": {
          "title": "Display Name",
          "type": "string"
        },
        "formula": {
          "title": "Formula",
          "type": "string"
        },
        "name": {
          "title": "Name",
          "type": "string"
        },
        "unit": {
          "title": "Unit",
          "type": "string"
        }
      },
      "required": [
        "name",
        "display_name",
        "description",
        "formula",
        "unit"
      ],
      "title": "KpiDefinition",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "definitions": {
      "items": {
        "$ref": "#/$defs/KpiDefinition"
      },
      "title": "Definitions",
      "type": "array"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    }
  },
  "required": [
    "definitions",
    "meta"
  ],
  "title": "KpiDefinitionsOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {},
  "tool": "get_kpi_definitions"
}
```

**Example response.**

```json
{
  "definitions": [
    {
      "description": "Total alarms in the selected scope and time range.",
      "display_name": "Alarm count",
      "formula": "count(alarms)",
      "name": "alarm_count",
      "unit": "alarms"
    },
    {
      "description": "Proportion of alarms that repeat an alarm name already seen in scope.",
      "display_name": "Recurring rate",
      "formula": "(count(alarms) - count(distinct alarm_name)) / count(alarms)",
      "name": "recurring_rate",
      "unit": "ratio"
    },
    {
      "description": "Mean seconds between alarm onset and operator acknowledgement.",
      "display_name": "Average acknowledgement delay",
      "formula": "mean(ack_time - start_time)",
      "name": "avg_ack_delay",
      "unit": "seconds"
    },
    {
      "description": "Alarms at critical severity.",
      "display_name": "Critical alarm count",
      "formula": "count(alarms where severity = 'critical')",
      "name": "critical_count",
      "unit": "alarms"
    },
    {
      "description": "Proportion of alarms belonging to names that recur at or above the rationalization threshold.",
      "display_name": "Suppression candidate rate",
      "formula": "count(alarms in names with count >= 5) / count(alarms)",
      "name": "suppression_candidate_rate",
      "unit": "ratio"
    }
  ],
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trac
  … truncated for the catalog
```

### `get_operator_recommendations`

**Purpose.** Ordered, actionable steps for an operator responding to a specific alarm.

Each action carries a rationale and its expected outcome, so the advice can be
    presented with its reasoning rather than as a bare list.

    The three include_* flags are opt-in because each costs an extra lookup. Enable
    all three when building a full investigation or an escalation summary.

**Underlying operation.** `POST /recommendations/operator-actions`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "alarm_id": {
      "description": "Alarm id to advise on",
      "title": "Alarm Id",
      "type": "string"
    },
    "include_asset_context": {
      "default": false,
      "description": "Include the asset's attributes",
      "title": "Include Asset Context",
      "type": "boolean"
    },
    "include_historical_pattern": {
      "default": false,
      "description": "Include 90-day recurrence statistics",
      "title": "Include Historical Pattern",
      "type": "boolean"
    },
    "include_related": {
      "default": false,
      "description": "Include alarms near it in time on the same asset",
      "title": "Include Related",
      "type": "boolean"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    }
  },
  "required": [
    "alarm_id"
  ],
  "title": "get_operator_recommendationsArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "AlarmRecord": {
      "properties": {
        "ack_delay_seconds": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Ack Delay Seconds"
        },
        "ack_time": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Ack Time"
        },
        "alarm_id": {
          "title": "Alarm Id",
          "type": "string"
        },
        "alarm_name": {
          "title": "Alarm Name",
          "type": "string"
        },
        "alarm_type": {
          "title": "Alarm Type",
          "type": "string"
        },
        "asset_id": {
          "title": "Asset Id",
          "type": "string"
        },
        "asset_name": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Asset Name"
        },
        "end_time": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "End Time"
        },
        "operator_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Operator Id"
        },
        "setpoint": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Setpoint"
        },
        "severity": {
          "title": "Severity",
          "type": "string"
        },
        "start_time": {
          "title": "Start Time",
          "type": "string"
        },
        "status": {
          "title": "Status",
          "type": "string"
        },
        "unit_of_measure": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Unit Of Measure"
        },
        "value": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Value"
        }
      },
      "required": [
        "alarm_id",
        "asset_id",
        "alarm_name",
        "alarm_type",
        "severity",
        "status",
        "start_time"
      ],
      "title": "AlarmRecord",
      "type": "object"
    },
    "HistoricalPattern": {
      "properties": {
        "is_recurring": {
          "title": "Is Recurring",
          "type": "boolean"
        },
        "mean_interval_hours": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Mean Interval Hours"
        },
        "occurrences_90d": {
          "title": "Occurrences 90D",
          "type": "integer"
        },
        "typical_ack_delay_seconds": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Typical Ack Delay Seconds"
        }
      },
      "required": [
        "occurrences_90d",
        "is_recurring"
      ],
      "title": "HistoricalPattern",
      "type": "object"
    },
    "RecommendedAction": {
      "properties": {
        "action": {
          "title": "Action",
          "type": "string"
        },
        "expected_outcome": {
          "title": "Expected Outcome",
          "type": "string"
        },
        "order": {
          "title": "Order",
          "type": "integer"
        },
        "rationale": {
          "title": "Rationale",
          "type": "string"
        }
      },
      "required": [
        "order",
        "action",
        "rationale",
        "expected_outcome"
      ],
      "title": "RecommendedAction",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "actions": {
      "items": {
        "$ref": "#/$defs/RecommendedAction"
      },
      "title": "Actions",
      "type": "array"
    },
    "alarm_id": {
      "title": "Alarm Id",
      "type": "string"
    },
    "alarm_name": {
      "title": "Alarm Name",
      "type": "string"
    },
    "asset_context": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Asset Context"
    },
    "historical_pattern": {
      "anyOf": [
        {
          "$ref": "#/$defs/HistoricalPattern"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "related_alarms": {
      "anyOf": [
        {
          "items": {
            "$ref": "#/$defs/AlarmRecord"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Related Alarms"
    },
    "severity": {
      "title": "Severity",
      "type": "string"
    }
  },
  "required": [
    "alarm_id",
    "alarm_name",
    "severity",
    "actions",
    "meta"
  ],
  "title": "OperatorActionsOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "alarm_id": "ALM-00069",
    "include_asset_context": true,
    "include_related": true
  },
  "tool": "get_operator_recommendations"
}
```

**Example response.**

```json
{
  "actions": [
    {
      "action": "Verify suction conditions, including strainer differential and tank level.",
      "expected_outcome": "Identifies whether the cause is suction-side.",
      "order": 1,
      "rationale": "Low discharge pressure most often originates upstream."
    },
    {
      "action": "Check for cavitation indicators \u2014 noise, vibration, erratic flow.",
      "expected_outcome": "Cavitation confirmed or excluded.",
      "order": 2,
      "rationale": "Cavitation damages impellers quickly if left running."
    },
    {
      "action": "If suction is normal, inspect the impeller and wear rings for wear.",
      "expected_outcome": "Mechanical condition established.",
      "order": 3,
      "rationale": "Internal wear reduces developed head."
    }
  ],
  "alarm_id": "ALM-00069",
  "alarm_name": "Discharge Pressure Low",
  "asset_context": {
    "active_alarms": 1,
    "asset_id": "AST-0005",
    "asset_name": "Boiler Feed Pump 101",
    "asset_type": "pump",
    "criticality": "high",
    "install_date": "2021-11-30T13:59:48.157382",
    "last_maintenance": "2025-09-24T13:59:48.157382",
    "manufacturer": "Emerson",
    "model": "PUM-4536",
    "site": "NorthPlant",
    "total_alarms": 46,
    "unit": "Unit 2"
  },
  "historical_pattern": null,
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-e2913002a093"
  },
  "relate
  … truncated for the catalog
```

### `get_priority_score`

**Purpose.** Score one alarm's priority from 0 to 100, with the reasoning broken out.

Combines alarm severity, asset criticality, how often the alarm recurs, and how
    long it went unacknowledged. Use to rank competing alarms.

    The `factors` array gives each component's weight and contribution. Quote those
    when explaining a ranking rather than restating the score — the breakdown is what
    makes the number defensible.

**Underlying operation.** `GET /alarms/{alarm_id}/priority-score`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "alarm_id": {
      "description": "Alarm id, e.g. ALM-00069",
      "title": "Alarm Id",
      "type": "string"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    }
  },
  "required": [
    "alarm_id"
  ],
  "title": "get_priority_scoreArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "PriorityFactor": {
      "properties": {
        "contribution": {
          "title": "Contribution",
          "type": "number"
        },
        "explanation": {
          "title": "Explanation",
          "type": "string"
        },
        "factor": {
          "title": "Factor",
          "type": "string"
        },
        "raw_value": {
          "title": "Raw Value",
          "type": "number"
        },
        "weight": {
          "title": "Weight",
          "type": "number"
        }
      },
      "required": [
        "factor",
        "weight",
        "raw_value",
        "contribution",
        "explanation"
      ],
      "title": "PriorityFactor",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "alarm_id": {
      "title": "Alarm Id",
      "type": "string"
    },
    "band": {
      "title": "Band",
      "type": "string"
    },
    "factors": {
      "description": "Per-factor breakdown, so a ranking can be explained rather than asserted",
      "items": {
        "$ref": "#/$defs/PriorityFactor"
      },
      "title": "Factors",
      "type": "array"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "priority_score": {
      "title": "Priority Score",
      "type": "number"
    }
  },
  "required": [
    "alarm_id",
    "priority_score",
    "band",
    "factors",
    "meta"
  ],
  "title": "PriorityScoreOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "alarm_id": "ALM-00069"
  },
  "tool": "get_priority_score"
}
```

**Example response.**

```json
{
  "alarm_id": "ALM-00069",
  "band": "critical",
  "factors": [
    {
      "contribution": 23.33,
      "explanation": "Alarm severity is high.",
      "factor": "severity",
      "raw_value": 0.6667,
      "weight": 0.35
    },
    {
      "contribution": 25.0,
      "explanation": "Asset criticality is high.",
      "factor": "asset_criticality",
      "raw_value": 1.0,
      "weight": 0.25
    },
    {
      "contribution": 25.0,
      "explanation": "This alarm name occurred 46 times on this asset.",
      "factor": "recurrence",
      "raw_value": 1.0,
      "weight": 0.25
    },
    {
      "contribution": 0.0,
      "explanation": "Not yet acknowledged.",
      "factor": "ack_delay",
      "raw_value": 0.0,
      "weight": 0.15
    }
  ],
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-45ec36fa3b23"
  },
  "priority_score": 73.33
}
```

### `get_rationalization_candidates`

**Purpose.** Identify alarms that should be re-tuned, suppressed, or chased up.

Two independent triggers, and the distinction matters because they call for
    different remedies. An alarm that *recurs* excessively usually needs its setpoint
    or deadband adjusted. An alarm that sits *stale* — active long past the threshold
    without acknowledgement — points at a workflow or workload problem instead.

    Each candidate carries the reason it was flagged and a recommended remedy.

**Underlying operation.** `POST /alarms/rationalization-candidates`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "asset_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Asset ids from search_assets. Omit to scope by unit or site instead.",
      "title": "Asset Ids"
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window end",
      "title": "End Time"
    },
    "recurrence_threshold": {
      "default": 5,
      "description": "Occurrences at or above which an alarm is flagged",
      "minimum": 1,
      "title": "Recurrence Threshold",
      "type": "integer"
    },
    "site": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant site, e.g. 'NorthPlant'",
      "title": "Site"
    },
    "stale_minutes_threshold": {
      "default": 180,
      "description": "Minutes an alarm may stay active before it is stale",
      "minimum": 1,
      "title": "Stale Minutes Threshold",
      "type": "integer"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "ISO-8601 window start, e.g. 2026-05-15T00:00:00Z",
      "title": "Start Time"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "title": "get_rationalization_candidatesArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "RationalizationCandidate": {
      "properties": {
        "alarm_name": {
          "title": "Alarm Name",
          "type": "string"
        },
        "asset_id": {
          "title": "Asset Id",
          "type": "string"
        },
        "asset_name": {
          "title": "Asset Name",
          "type": "string"
        },
        "occurrences": {
          "title": "Occurrences",
          "type": "integer"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        },
        "recommendation": {
          "title": "Recommendation",
          "type": "string"
        },
        "stale_count": {
          "title": "Stale Count",
          "type": "integer"
        }
      },
      "required": [
        "asset_id",
        "asset_name",
        "alarm_name",
        "occurrences",
        "stale_count",
        "reason",
        "recommendation"
      ],
      "title": "RationalizationCandidate",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "candidates": {
      "items": {
        "$ref": "#/$defs/RationalizationCandidate"
      },
      "title": "Candidates",
      "type": "array"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "recurrence_threshold": {
      "title": "Recurrence Threshold",
      "type": "integer"
    },
    "stale_minutes_threshold": {
      "title": "Stale Minutes Threshold",
      "type": "integer"
    }
  },
  "required": [
    "candidates",
    "recurrence_threshold",
    "stale_minutes_threshold",
    "meta"
  ],
  "title": "RationalizationOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "asset_ids": [
      "AST-0005"
    ],
    "end_time": "2026-08-13T13:59:48.916104+00:00",
    "recurrence_threshold": 5,
    "start_time": "2026-05-15T13:59:48.916104+00:00"
  },
  "tool": "get_rationalization_candidates"
}
```

**Example response.**

```json
{
  "candidates": [
    {
      "alarm_name": "Discharge Pressure Low",
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "occurrences": 45,
      "reason": "occurred 45 times, at or above the threshold of 5; 1 occurrence(s) still active beyond 180 minutes",
      "recommendation": "Review setpoint and deadband, and investigate why occurrences are not being acknowledged.",
      "stale_count": 1
    },
    {
      "alarm_name": "Suction Strainer DP High",
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "occurrences": 43,
      "reason": "occurred 43 times, at or above the threshold of 5",
      "recommendation": "Candidate for setpoint or deadband re-tuning, or suppression during known transients.",
      "stale_count": 0
    },
    {
      "alarm_name": "Bearing Temperature High",
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "occurrences": 18,
      "reason": "occurred 18 times, at or above the threshold of 5; 2 occurrence(s) still active beyond 180 minutes",
      "recommendation": "Review setpoint and deadband, and investigate why occurrences are not being acknowledged.",
      "stale_count": 2
    },
    {
      "alarm_name": "Vibration High",
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "occurrences": 18,
      "reason": "occurred 18 times, at
  … truncated for the catalog
```

### `search_assets`

**Purpose.** Resolve a free-text asset name or type to structured asset records.

Start here for any question that names equipment. Almost every other tool needs
    an asset_id, and this is the only tool that produces one from a human name.
    Matching is case-insensitive and partial, so 'compressor' returns every
    compressor.

**Underlying operation.** `GET /assets/search`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "limit": {
      "default": 10,
      "description": "Maximum results",
      "maximum": 100,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    },
    "query": {
      "description": "Free text matched against asset name and type, e.g. 'Boiler Feed Pump 101' or 'compressor'",
      "title": "Query",
      "type": "string"
    },
    "trace_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Correlation id to propagate to the source system. Generated if omitted.",
      "title": "Trace Id"
    },
    "unit": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Plant unit, e.g. 'Unit 2'",
      "title": "Unit"
    }
  },
  "required": [
    "query"
  ],
  "title": "search_assetsArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "AssetSummary": {
      "properties": {
        "asset_id": {
          "title": "Asset Id",
          "type": "string"
        },
        "asset_name": {
          "title": "Asset Name",
          "type": "string"
        },
        "asset_type": {
          "title": "Asset Type",
          "type": "string"
        },
        "criticality": {
          "title": "Criticality",
          "type": "string"
        },
        "site": {
          "title": "Site",
          "type": "string"
        },
        "unit": {
          "title": "Unit",
          "type": "string"
        }
      },
      "required": [
        "asset_id",
        "asset_name",
        "asset_type",
        "unit",
        "site",
        "criticality"
      ],
      "title": "AssetSummary",
      "type": "object"
    },
    "ToolMeta": {
      "description": "Execution metadata attached to every tool result.",
      "properties": {
        "source": {
          "default": "alarm-management-api",
          "description": "System that answered",
          "title": "Source",
          "type": "string"
        },
        "trace_id": {
          "description": "Correlation id propagated to the source system",
          "title": "Trace Id",
          "type": "string"
        }
      },
      "required": [
        "trace_id"
      ],
      "title": "ToolMeta",
      "type": "object"
    }
  },
  "properties": {
    "count": {
      "title": "Count",
      "type": "integer"
    },
    "meta": {
      "$ref": "#/$defs/ToolMeta"
    },
    "query": {
      "title": "Query",
      "type": "string"
    },
    "results": {
      "items": {
        "$ref": "#/$defs/AssetSummary"
      },
      "title": "Results",
      "type": "array"
    }
  },
  "required": [
    "query",
    "count",
    "results",
    "meta"
  ],
  "title": "SearchAssetsOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "limit": 3,
    "query": "Boiler Feed Pump 101"
  },
  "tool": "search_assets"
}
```

**Example response.**

```json
{
  "count": 1,
  "meta": {
    "source": "alarm-management-api",
    "trace_id": "trace-98c8e9b1433c"
  },
  "query": "Boiler Feed Pump 101",
  "results": [
    {
      "asset_id": "AST-0005",
      "asset_name": "Boiler Feed Pump 101",
      "asset_type": "pump",
      "criticality": "high",
      "site": "NorthPlant",
      "unit": "Unit 2"
    }
  ]
}
```

## Server: `github-issues`

### `create_issue`

**Purpose.** Create a real issue. **Requires explicit human confirmation.**

This is a write. It refuses unless `confirmed` is true, and that flag is set by
    the user approving the draft in the interface — not by you.

    If you have not yet shown the user a draft from draft_issue, do that first.

**Underlying operation.** `POST /repos/{owner}/{repo}/issues (mock backend by default)`

**Authentication.** Server-held bearer token; never a tool argument.  
**Write gate.** Refuses with `CONFIRMATION_REQUIRED` unless `confirmed: true` is passed, which only an explicit human approval sets.

**Input schema.**

```json
{
  "properties": {
    "body": {
      "description": "Issue body, normally from draft_issue",
      "title": "Body",
      "type": "string"
    },
    "confirmed": {
      "default": false,
      "description": "Must be true. Set only after a human has seen the draft and approved it. Do not set this yourself.",
      "title": "Confirmed",
      "type": "boolean"
    },
    "labels": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Labels to apply",
      "title": "Labels"
    },
    "title": {
      "description": "Issue title, normally from draft_issue",
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "title",
    "body"
  ],
  "title": "create_issueArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "properties": {
    "created": {
      "title": "Created",
      "type": "boolean"
    },
    "number": {
      "title": "Number",
      "type": "integer"
    },
    "state": {
      "title": "State",
      "type": "string"
    },
    "title": {
      "title": "Title",
      "type": "string"
    },
    "url": {
      "title": "Url",
      "type": "string"
    }
  },
  "required": [
    "number",
    "title",
    "url",
    "state",
    "created"
  ],
  "title": "CreateIssueOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "body": "See the alarm summary and OP-BFP-101 \u00a74.",
    "confirmed": true,
    "title": "Recurring suction strainer alarms on Boiler Feed Pump 101"
  },
  "tool": "create_issue"
}
```

**Example response.**

```json
{
  "created": true,
  "number": 200,
  "state": "open",
  "title": "Recurring suction strainer alarms on Boiler Feed Pump 101",
  "url": "https://github.com/example/plant-ops/issues/200"
}
```

### `draft_issue`

**Purpose.** Compose an issue from findings. **Writes nothing.**

A pure function: it formats text and returns it. Call it freely — nothing is
    created, and no confirmation is needed to draft.

    Show the result to the user. Creating the issue is a separate, explicitly
    confirmed step.

**Underlying operation.** `none — a pure function, no I/O`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "evidence": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Supporting findings, one per line. Include tool and source citations here so the issue carries its provenance.",
      "title": "Evidence"
    },
    "labels": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Labels to apply",
      "title": "Labels"
    },
    "recommended_actions": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "What should be done, in order",
      "title": "Recommended Actions"
    },
    "summary": {
      "description": "What was found \u2014 the evidence and its significance",
      "title": "Summary",
      "type": "string"
    },
    "title": {
      "description": "One-line summary of the problem",
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "title",
    "summary"
  ],
  "title": "draft_issueArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "properties": {
    "body": {
      "title": "Body",
      "type": "string"
    },
    "confirmation_required": {
      "default": true,
      "description": "Present this draft to the user. create_issue will refuse without their explicit confirmation.",
      "title": "Confirmation Required",
      "type": "boolean"
    },
    "is_draft": {
      "default": true,
      "description": "Always true. This tool writes nothing; nothing has been created.",
      "title": "Is Draft",
      "type": "boolean"
    },
    "labels": {
      "items": {
        "type": "string"
      },
      "title": "Labels",
      "type": "array"
    },
    "title": {
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "title",
    "body",
    "labels"
  ],
  "title": "DraftIssueOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "labels": [
      "alarm-rationalization"
    ],
    "summary": "39 high-severity alarms in 90 days, correlated with discharge pressure low.",
    "title": "Recurring suction strainer alarms on Boiler Feed Pump 101"
  },
  "tool": "draft_issue"
}
```

**Example response.**

```json
{
  "body": "39 high-severity alarms in 90 days, correlated with discharge pressure low.\n\n_Drafted by the Multi-MCP Enterprise Operations Copilot._",
  "confirmation_required": true,
  "is_draft": true,
  "labels": [
    "alarm-rationalization"
  ],
  "title": "Recurring suction strainer alarms on Boiler Feed Pump 101"
}
```

### `search_issues`

**Purpose.** Search existing issues. Read-only.

Use this **before** drafting anything. If the problem is already tracked, saying
    so is more useful than filing a duplicate, and the existing issue usually carries
    context worth referencing.

**Underlying operation.** `GET /search/issues (mock backend by default)`

**Authentication.** Server-held bearer token; never a tool argument.

**Input schema.**

```json
{
  "properties": {
    "limit": {
      "default": 10,
      "description": "Maximum results",
      "maximum": 50,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    },
    "query": {
      "description": "Text to match against issue titles and bodies, e.g. an asset name like 'Boiler Feed Pump 101'",
      "title": "Query",
      "type": "string"
    }
  },
  "required": [
    "query"
  ],
  "title": "search_issuesArguments",
  "type": "object"
}
```

**Output schema.**

```json
{
  "$defs": {
    "IssueSummary": {
      "properties": {
        "labels": {
          "items": {
            "type": "string"
          },
          "title": "Labels",
          "type": "array"
        },
        "number": {
          "title": "Number",
          "type": "integer"
        },
        "state": {
          "title": "State",
          "type": "string"
        },
        "title": {
          "title": "Title",
          "type": "string"
        },
        "url": {
          "title": "Url",
          "type": "string"
        }
      },
      "required": [
        "number",
        "title",
        "labels",
        "state",
        "url"
      ],
      "title": "IssueSummary",
      "type": "object"
    }
  },
  "properties": {
    "count": {
      "title": "Count",
      "type": "integer"
    },
    "issues": {
      "items": {
        "$ref": "#/$defs/IssueSummary"
      },
      "title": "Issues",
      "type": "array"
    },
    "query": {
      "title": "Query",
      "type": "string"
    }
  },
  "required": [
    "query",
    "count",
    "issues"
  ],
  "title": "SearchIssuesOutput",
  "type": "object"
}
```

**Example invocation.**

```json
{
  "arguments": {
    "limit": 3,
    "query": "Boiler Feed Pump 101"
  },
  "tool": "search_issues"
}
```

**Example response.**

```json
{
  "count": 1,
  "issues": [
    {
      "labels": [
        "operations"
      ],
      "number": 200,
      "state": "open",
      "title": "Recurring suction strainer alarms on Boiler Feed Pump 101",
      "url": "https://github.com/example/plant-ops/issues/200"
    }
  ],
  "query": "Boiler Feed Pump 101"
}
```
