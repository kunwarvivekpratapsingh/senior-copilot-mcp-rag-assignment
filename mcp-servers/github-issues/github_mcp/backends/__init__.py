"""Issue-tracker backends: an in-memory mock and the real GitHub REST API."""

from .base import Issue, IssueBackend
from .mock import MockIssueBackend

__all__ = ["Issue", "IssueBackend", "MockIssueBackend"]
