"""Issue-tracker backend interface.

Two implementations sit behind this: an in-memory mock (the demo default, so the
system runs with no credentials and no network) and the real GitHub REST API. Both
satisfy the same protocol, so the MCP tools are written once and neither the tools
nor their tests know which is in use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    url: str = ""


class IssueBackend(Protocol):
    """What the tools need from an issue tracker."""

    async def search(self, query: str, limit: int) -> list[Issue]: ...

    async def create(self, title: str, body: str, labels: list[str]) -> Issue: ...
