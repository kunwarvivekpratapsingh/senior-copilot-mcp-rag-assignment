"""Placeholder resolution — LLD §5.6.

This is what "multi-step tool chaining" means concretely. A plan step may reference a
value produced by an earlier step:

    "$s1.output.results[0].asset_id"

which is substituted once step ``s1`` has returned. It is the same dependency the
supplied Postman chaining collection expresses with ``pm.collectionVariables.set()``.

Grammar::

    $<stepId>.output(.<key>|[<index>])*

Unresolvable references raise rather than silently becoming ``None``. A step that
quietly runs with a missing argument produces a plausible-looking wrong answer, which
is worse than a clear failure.
"""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER = re.compile(r"^\$(?P<step>[A-Za-z0-9_]+)\.output(?P<path>.*)$")
_SEGMENT = re.compile(r"\.([A-Za-z0-9_]+)|\[(\d+)\]")


class PlaceholderError(ValueError):
    """A reference could not be resolved against the results collected so far."""


def is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("$") and ".output" in value


def resolve_path(payload: Any, path: str, *, reference: str) -> Any:
    """Walk a dotted/indexed path into a tool's output."""
    current = payload
    for match in _SEGMENT.finditer(path):
        key, index = match.group(1), match.group(2)
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                available = (
                    ", ".join(sorted(current)) if isinstance(current, dict) else type(current).__name__
                )
                raise PlaceholderError(
                    f"{reference}: no key '{key}'. Available: {available}"
                )
            current = current[key]
        else:
            position = int(index)  # type: ignore[arg-type]
            if not isinstance(current, list):
                raise PlaceholderError(f"{reference}: expected a list to index with [{position}]")
            if position >= len(current):
                raise PlaceholderError(
                    f"{reference}: index [{position}] out of range; "
                    f"the earlier step returned {len(current)} item(s)"
                )
            current = current[position]
    return current


def resolve_value(value: Any, outputs: dict[str, dict[str, Any]]) -> Any:
    """Recursively substitute placeholders inside an argument value."""
    if isinstance(value, str) and is_placeholder(value):
        match = PLACEHOLDER.match(value)
        if match is None:
            raise PlaceholderError(f"malformed placeholder: {value!r}")
        step_id = match.group("step")
        if step_id not in outputs:
            known = ", ".join(sorted(outputs)) or "none yet"
            raise PlaceholderError(
                f"{value}: step '{step_id}' has not produced output. Completed: {known}"
            )
        return resolve_path(outputs[step_id], match.group("path"), reference=value)
    if isinstance(value, dict):
        return {k: resolve_value(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, outputs) for v in value]
    return value


def resolve_args(
    args: dict[str, Any], outputs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Substitute every placeholder in a step's arguments."""
    return {key: resolve_value(value, outputs) for key, value in args.items()}


def referenced_steps(args: Any) -> set[str]:
    """Which earlier steps a set of arguments depends on.

    Used to skip a step whose dependency failed, rather than running it with a
    placeholder that cannot resolve.
    """
    found: set[str] = set()
    if isinstance(args, str) and is_placeholder(args):
        if match := PLACEHOLDER.match(args):
            found.add(match.group("step"))
    elif isinstance(args, dict):
        for value in args.values():
            found |= referenced_steps(value)
    elif isinstance(args, list):
        for value in args:
            found |= referenced_steps(value)
    return found
