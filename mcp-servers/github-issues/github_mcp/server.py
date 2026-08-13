"""GitHub Issues MCP server.

The second MCP server. It satisfies the "at least two servers" requirement, answers
the brief's "prepare a GitHub issue draft" example, and — more importantly — is where
the write-approval boundary lives.

Run standalone::

    python -m github_mcp                      # stdio
    python -m github_mcp --transport http     # streamable HTTP

**The write gate is enforced in the tool contract, not in the UI.** ``create_issue``
refuses unless ``confirmed=true``. A dialog in the browser is what sets that flag
after a human approves the draft — but a gate that lived only in the UI would be
bypassed by any other caller, including the language model itself. Enforcing it here
means the guarantee holds for every caller and is unit-testable without a browser.

The three tools are deliberately split so that drafting is separable from writing:
``draft_issue`` is a pure function that composes text and returns it. Nothing it can
do has a side effect, so the model is free to call it while exploring.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from .backends.base import Issue, IssueBackend
from .backends.mock import MockIssueBackend
from .config import Settings, get_settings
from .logging import configure_logging, get_logger

logger = get_logger(__name__)

mcp = MCPServer(
    name="github-issues",
    version="1.0.0",
    instructions=(
        "Issue tracking for plant operations. Before drafting, use search_issues to "
        "check whether the problem is already tracked. draft_issue composes an issue "
        "and writes nothing — always draft first and show the result to the user. "
        "create_issue performs a real write and requires explicit human confirmation."
    ),
)

_backend: IssueBackend | None = None


def get_backend(settings: Settings | None = None) -> IssueBackend:
    global _backend
    if _backend is None:
        settings = settings or get_settings()
        if settings.github_mock:
            _backend = MockIssueBackend()
        else:
            from .backends.github_rest import GitHubRestBackend

            _backend = GitHubRestBackend(settings.github_token, settings.github_repo)
    return _backend


def set_backend(backend: IssueBackend | None) -> None:
    """Replace the backend. Used by tests."""
    global _backend
    _backend = backend


# --------------------------------------------------------------------------- #
# Output contracts
# --------------------------------------------------------------------------- #


class IssueSummary(BaseModel):
    number: int
    title: str
    labels: list[str]
    state: str
    url: str


class SearchIssuesOutput(BaseModel):
    query: str
    count: int
    issues: list[IssueSummary]


class DraftIssueOutput(BaseModel):
    title: str
    body: str
    labels: list[str]
    is_draft: bool = Field(
        default=True,
        description="Always true. This tool writes nothing; nothing has been created.",
    )
    confirmation_required: bool = Field(
        default=True,
        description="Present this draft to the user. create_issue will refuse without "
        "their explicit confirmation.",
    )


class CreateIssueOutput(BaseModel):
    number: int
    title: str
    url: str
    state: str
    created: bool


def _summary(issue: Issue) -> IssueSummary:
    return IssueSummary(
        number=issue.number,
        title=issue.title,
        labels=issue.labels,
        state=issue.state,
        url=issue.url,
    )


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


@mcp.tool()
async def search_issues(
    query: Annotated[
        str, Field(description="Text to match against issue titles and bodies, "
                               "e.g. an asset name like 'Boiler Feed Pump 101'")
    ],
    limit: Annotated[int, Field(description="Maximum results", ge=1, le=50)] = 10,
) -> SearchIssuesOutput:
    """Search existing issues. Read-only.

    Use this **before** drafting anything. If the problem is already tracked, saying
    so is more useful than filing a duplicate, and the existing issue usually carries
    context worth referencing.
    """
    issues = await get_backend().search(query, limit)
    logger.info("issues_searched", mcp_tool="search_issues", query=query, hits=len(issues))
    return SearchIssuesOutput(
        query=query, count=len(issues), issues=[_summary(i) for i in issues]
    )


@mcp.tool()
async def draft_issue(
    title: Annotated[str, Field(description="One-line summary of the problem")],
    summary: Annotated[
        str, Field(description="What was found — the evidence and its significance")
    ],
    evidence: Annotated[
        list[str] | None,
        Field(description="Supporting findings, one per line. Include tool and source "
                          "citations here so the issue carries its provenance."),
    ] = None,
    recommended_actions: Annotated[
        list[str] | None, Field(description="What should be done, in order")
    ] = None,
    labels: Annotated[list[str] | None, Field(description="Labels to apply")] = None,
) -> DraftIssueOutput:
    """Compose an issue from findings. **Writes nothing.**

    A pure function: it formats text and returns it. Call it freely — nothing is
    created, and no confirmation is needed to draft.

    Show the result to the user. Creating the issue is a separate, explicitly
    confirmed step.
    """
    sections = [summary.strip()]
    if evidence:
        sections.append("## Evidence\n" + "\n".join(f"- {item}" for item in evidence))
    if recommended_actions:
        sections.append(
            "## Recommended actions\n"
            + "\n".join(f"{i}. {a}" for i, a in enumerate(recommended_actions, 1))
        )
    sections.append("_Drafted by the Multi-MCP Enterprise Operations Copilot._")

    logger.info("issue_drafted", mcp_tool="draft_issue", title=title)
    return DraftIssueOutput(
        title=title, body="\n\n".join(sections), labels=labels or ["operations"]
    )


@mcp.tool()
async def create_issue(
    title: Annotated[str, Field(description="Issue title, normally from draft_issue")],
    body: Annotated[str, Field(description="Issue body, normally from draft_issue")],
    confirmed: Annotated[
        bool,
        Field(
            description="Must be true. Set only after a human has seen the draft and "
            "approved it. Do not set this yourself."
        ),
    ] = False,
    labels: Annotated[list[str] | None, Field(description="Labels to apply")] = None,
) -> CreateIssueOutput:
    """Create a real issue. **Requires explicit human confirmation.**

    This is a write. It refuses unless `confirmed` is true, and that flag is set by
    the user approving the draft in the interface — not by you.

    If you have not yet shown the user a draft from draft_issue, do that first.
    """
    if not confirmed:
        # The refusal is the feature. Enforcing it here rather than in the UI means
        # the guarantee holds for every caller.
        logger.warning("issue_creation_refused", mcp_tool="create_issue", reason="unconfirmed")
        raise ValueError(
            "[CONFIRMATION_REQUIRED] create_issue refused: this is a write operation and "
            "requires explicit human confirmation. Present the draft to the user and "
            "call again with confirmed=true only after they approve."
        )

    issue = await get_backend().create(title, body, labels or ["operations"])
    logger.info(
        "issue_created", mcp_tool="create_issue", issue_number=issue.number, outcome="success"
    )
    return CreateIssueOutput(
        number=issue.number, title=issue.title, url=issue.url, state=issue.state, created=True
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="GitHub Issues MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "mcp_server_starting",
        mcp_server="github-issues",
        transport=args.transport,
        backend="mock" if settings.github_mock else "github-rest",
        tool_count=3,
    )

    if args.transport == "http":
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_github_host,
            port=settings.mcp_github_port,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
