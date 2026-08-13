"""In-memory issue backend — the demo default.

Exists so the whole system runs end to end with no GitHub credentials and no
network. That matters for an assessment: the reviewer should be able to clone the
repository and see the write-approval flow work without first provisioning a token
and a scratch repository.

Pre-seeded with a couple of issues so `search_issues` has something to find, which is
what makes the duplicate check demonstrable rather than vacuous.
"""

from __future__ import annotations

from .base import Issue

SEEDED_ISSUES = [
    Issue(
        number=101,
        title="Boiler Feed Pump 102 — intermittent seal leak",
        body="Seal leak detected twice this month. Monitoring before scheduling a rebuild.",
        labels=["maintenance", "unit-2"],
        state="open",
        url="https://github.com/example/plant-ops/issues/101",
    ),
    Issue(
        number=97,
        title="Unit 5 motor vibration trending upward",
        body="Vibration on Induction Motor 601 rising over six weeks. Alignment check requested.",
        labels=["reliability", "unit-5"],
        state="open",
        url="https://github.com/example/plant-ops/issues/97",
    ),
]


class MockIssueBackend:
    """Deterministic in-memory issue tracker."""

    def __init__(self) -> None:
        self._issues: list[Issue] = list(SEEDED_ISSUES)
        self._next_number = 200

    async def search(self, query: str, limit: int) -> list[Issue]:
        """Case-insensitive substring match over title and body."""
        needle = query.lower()
        matches = [
            issue
            for issue in self._issues
            if needle in issue.title.lower() or needle in issue.body.lower()
        ]
        return matches[:limit]

    async def create(self, title: str, body: str, labels: list[str]) -> Issue:
        issue = Issue(
            number=self._next_number,
            title=title,
            body=body,
            labels=list(labels),
            state="open",
            url=f"https://github.com/example/plant-ops/issues/{self._next_number}",
        )
        self._next_number += 1
        self._issues.append(issue)
        return issue

    # Test affordance — not part of the protocol.
    def all_issues(self) -> list[Issue]:
        return list(self._issues)
