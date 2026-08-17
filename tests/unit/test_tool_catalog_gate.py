"""Tests for the generated tool catalog's drift gate — T-DOC-01..05.

The gate exists so that a changed tool schema cannot be merged with a stale catalog.
It is only worth having if it fires on that and stays quiet otherwise: CI failed on the
first push because the comparison included captured example responses, whose values
move with the seeded data's sliding window. These tests pin both halves of that
behaviour.

The catalog file itself is checked by ``python scripts/gen_tool_catalog.py --check`` in
CI, which needs the MCP servers; this module tests the comparison logic alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gen_tool_catalog import normalise, strip_example_responses  # noqa: E402

CATALOG = REPO_ROOT / "docs" / "mcp-tool-catalog.md"

SAMPLE = """\
### `search_assets`

**Purpose.** Resolve a free-text asset name.

**Input schema.**

```json
{
  "properties": {
    "query": {"type": "string"}
  }
}
```

**Example response.**

```json
{
  "count": 3,
  "results": [{"asset_id": "AST-0005", "last_maintenance": "2026-06-01T00:00:00Z"}]
}
```

### `get_alarms`

**Purpose.** List alarms.
"""


class TestExampleStripping:
    def test_the_example_response_body_is_dropped(self) -> None:
        stripped = strip_example_responses(SAMPLE)
        assert '"count": 3' not in stripped
        assert "AST-0005" not in stripped

    def test_everything_else_survives(self) -> None:
        """Only the captured output goes. The contract has to remain comparable."""
        stripped = strip_example_responses(SAMPLE)
        assert "### `search_assets`" in stripped
        assert "Resolve a free-text asset name." in stripped
        assert '"query": {"type": "string"}' in stripped
        assert "### `get_alarms`" in stripped
        # The heading itself stays, so a missing section is still visible.
        assert "**Example response.**" in stripped


class TestDriftDetection:
    def test_a_changed_schema_is_detected(self) -> None:
        changed = SAMPLE.replace('"query": {"type": "string"}', '"q": {"type": "string"}')
        assert normalise(changed) != normalise(SAMPLE)

    def test_a_changed_description_is_detected(self) -> None:
        """Descriptions are what the planner selects tools from, so they are contract."""
        changed = SAMPLE.replace("Resolve a free-text asset name.", "Find things.")
        assert normalise(changed) != normalise(SAMPLE)

    def test_a_removed_tool_is_detected(self) -> None:
        changed = SAMPLE.replace("### `get_alarms`\n\n**Purpose.** List alarms.\n", "")
        assert normalise(changed) != normalise(SAMPLE)

    def test_different_captured_data_is_not_a_failure(self) -> None:
        """The case that broke CI: same contract, different seeded values."""
        later = SAMPLE.replace('"count": 3', '"count": 4').replace(
            "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z"
        )
        assert normalise(later) == normalise(SAMPLE)

    def test_a_moved_clock_is_not_a_failure(self) -> None:
        """Timestamps and generated ids appear in example invocations too."""
        later = (
            SAMPLE
            + "\n**Example invocation.**\n\n```json\n"
            + '{"start_time": "2026-08-17T10:00:00Z", "calculation_id": "CALC-abc123"}\n```\n'
        )
        earlier = (
            SAMPLE
            + "\n**Example invocation.**\n\n```json\n"
            + '{"start_time": "2026-05-01T10:00:00Z", "calculation_id": "CALC-def456"}\n```\n'
        )
        assert normalise(later) == normalise(earlier)


class TestCommittedCatalog:
    def test_the_catalog_is_committed_and_covers_every_tool(self) -> None:
        text = CATALOG.read_text(encoding="utf-8")
        assert text.count("### `") == 17
        assert "GENERATED FILE" in text

    def test_the_catalog_carries_the_mandated_fields(self) -> None:
        text = CATALOG.read_text(encoding="utf-8")
        for field in (
            "**Purpose.**", "**Input schema.**", "**Output schema.**",
            "**Underlying operation.**", "**Authentication.**",
            "**Example invocation.**", "**Example response.**",
        ):
            assert text.count(field) >= 17, f"{field} is missing from some tools"

    def test_no_credential_appears_in_the_catalog(self) -> None:
        """Every example is real output; a leak here would be published documentation."""
        text = CATALOG.read_text(encoding="utf-8")
        assert "demo-token" not in text
        assert "Authorization" not in text
