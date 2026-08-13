# MCP tool catalog

Complete reference for all 17 tools across the two candidate-built MCP servers.

Each tool documents the ten fields required by Submission_and_Evaluation_Guidelines.md
§5: tool name, purpose, input schema, output schema, authentication behaviour,
underlying source-system operation, error behaviour, timeout behaviour, example
invocation, and example response.

> **Pending — generated in build step 12 by `scripts/gen_tool_catalog.py`.**

This file is generated from the Pydantic models that define the tools, not written by
hand, so it cannot drift from the implementation. `make docs` regenerates it; CI asserts
that regenerating produces no git diff.

| Server | Tools |
|---|---|
| `alarm-management` | 14 — asset search and metadata, alarm retrieval, summary, trends, correlation, flood analysis, rationalization, priority scoring, operator recommendations, calculation generate/execute, KPI definitions |
| `github-issues` | 3 — issue search, issue drafting, gated issue creation |
