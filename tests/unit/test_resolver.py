"""Placeholder resolver tests — T-RES-01..10. Covers FR-05 (chaining), LLD §5.6.

The resolver is the mechanism behind "the output of one tool becomes the input of
the next", so its failure behaviour matters as much as its success behaviour: a
reference that silently becomes ``None`` produces a confident wrong answer, which is
the single worst outcome this system can produce.
"""

from __future__ import annotations

import pytest
from copilot_backend.orchestrator.resolver import (
    PlaceholderError,
    is_placeholder,
    referenced_steps,
    resolve_args,
)

OUTPUTS = {
    "s1": {
        "count": 2,
        "results": [
            {"asset_id": "AST-0007", "asset_name": "Boiler Feed Pump 101"},
            {"asset_id": "AST-0008", "asset_name": "Boiler Feed Pump 102"},
        ],
    },
    "s2": {"calculation_id": "CALC-0001", "nested": {"deep": {"value": 42}}},
}


class TestRecognition:
    @pytest.mark.parametrize(
        "value",
        ["$s1.output.results[0].asset_id", "$s2.output.calculation_id", "$s1.output"],
    )
    def test_placeholders_are_recognised(self, value: str) -> None:
        assert is_placeholder(value)

    @pytest.mark.parametrize("value", ["AST-0007", "$100.00", "the $ sign", ""])
    def test_ordinary_strings_are_not(self, value: str) -> None:
        assert not is_placeholder(value)


class TestResolution:
    def test_array_index_then_key(self) -> None:
        resolved = resolve_args({"asset_ids": ["$s1.output.results[0].asset_id"]}, OUTPUTS)
        assert resolved == {"asset_ids": ["AST-0007"]}

    def test_a_second_index_selects_a_different_item(self) -> None:
        resolved = resolve_args({"a": "$s1.output.results[1].asset_name"}, OUTPUTS)
        assert resolved == {"a": "Boiler Feed Pump 102"}

    def test_plain_key(self) -> None:
        assert resolve_args({"calculation_id": "$s2.output.calculation_id"}, OUTPUTS) == {
            "calculation_id": "CALC-0001"
        }

    def test_deeply_nested_keys(self) -> None:
        assert resolve_args({"v": "$s2.output.nested.deep.value"}, OUTPUTS) == {"v": 42}

    def test_an_empty_path_yields_the_whole_output(self) -> None:
        assert resolve_args({"all": "$s2.output"}, OUTPUTS)["all"] == OUTPUTS["s2"]

    def test_placeholders_nested_inside_structures_are_resolved(self) -> None:
        """Plans put references inside lists and objects, not only at the top level."""
        resolved = resolve_args(
            {
                "filters": {"asset_ids": ["$s1.output.results[0].asset_id"]},
                "labels": ["alarm", "$s1.output.results[0].asset_name"],
            },
            OUTPUTS,
        )
        assert resolved["filters"]["asset_ids"] == ["AST-0007"]
        assert resolved["labels"] == ["alarm", "Boiler Feed Pump 101"]

    def test_non_placeholder_values_pass_through_untouched(self) -> None:
        args = {"severity": ["high", "critical"], "limit": 5, "flag": True, "none": None}
        assert resolve_args(args, OUTPUTS) == args


class TestFailure:
    def test_a_reference_to_a_step_that_has_not_run_raises(self) -> None:
        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"a": "$s9.output.value"}, OUTPUTS)
        assert "s9" in str(caught.value)
        assert "s1" in str(caught.value)  # tells the caller what *did* complete

    def test_an_unknown_key_names_the_available_ones(self) -> None:
        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"a": "$s1.output.rows[0].asset_id"}, OUTPUTS)
        assert "results" in str(caught.value)

    def test_an_index_past_the_end_says_how_many_there_were(self) -> None:
        """The usual cause is an earlier step returning fewer results than the plan
        assumed — the count is what makes that diagnosable."""
        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"a": "$s1.output.results[5].asset_id"}, OUTPUTS)
        assert "2 item(s)" in str(caught.value)

    def test_indexing_something_that_is_not_a_list_raises(self) -> None:
        with pytest.raises(PlaceholderError):
            resolve_args({"a": "$s2.output.calculation_id[0]"}, OUTPUTS)


class TestDependencyDetection:
    def test_finds_the_steps_a_set_of_arguments_depends_on(self) -> None:
        deps = referenced_steps(
            {"a": "$s1.output.results[0].asset_id", "b": {"c": ["$s2.output.calculation_id"]}}
        )
        assert deps == {"s1", "s2"}

    def test_arguments_with_no_references_depend_on_nothing(self) -> None:
        assert referenced_steps({"query": "pump", "limit": 5}) == set()
