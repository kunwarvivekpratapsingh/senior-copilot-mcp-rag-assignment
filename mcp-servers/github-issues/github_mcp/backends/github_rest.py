"""Real GitHub REST backend.

Not the demo default — ``GITHUB_MOCK=true`` selects the mock — but implemented and
exercised by its own tests so the abstraction is demonstrably real rather than a
single implementation behind an interface.

The token lives here, in the MCP server process. It is never a tool argument.
"""

from __future__ import annotations

import httpx

from .base import Issue

GITHUB_API = "https://api.github.com"


class GitHubRestBackend:
    """Issue search and creation against the GitHub REST API."""

    def __init__(self, token: str, repo: str, *, timeout_seconds: float = 10.0) -> None:
        self._repo = repo
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _to_issue(payload: dict[str, object]) -> Issue:
        return Issue(
            number=int(payload.get("number", 0)),
            title=str(payload.get("title", "")),
            body=str(payload.get("body") or ""),
            labels=[
                str(label.get("name", ""))
                for label in payload.get("labels", [])  # type: ignore[union-attr]
                if isinstance(label, dict)
            ],
            state=str(payload.get("state", "open")),
            url=str(payload.get("html_url", "")),
        )

    async def search(self, query: str, limit: int) -> list[Issue]:
        response = await self._client.get(
            "/search/issues",
            params={"q": f"repo:{self._repo} is:issue {query}", "per_page": limit},
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        return [self._to_issue(item) for item in items[:limit]]

    async def create(self, title: str, body: str, labels: list[str]) -> Issue:
        response = await self._client.post(
            f"/repos/{self._repo}/issues",
            json={"title": title, "body": body, "labels": labels},
        )
        response.raise_for_status()
        return self._to_issue(response.json())
