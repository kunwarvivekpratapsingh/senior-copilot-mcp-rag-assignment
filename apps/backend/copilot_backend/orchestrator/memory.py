"""Conversation memory — FR-16.

In-process and bounded. Multi-turn context is a functional requirement, but persisting
it is not, and an unbounded store in a demo is a slow memory leak. Moving this to Redis
is the change that makes the backend horizontally scalable; it is noted in
known-limitations.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

MAX_TURNS = 6


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str
    intent: str


class ConversationMemory:
    """Recent turns per conversation."""

    def __init__(self, max_turns: int = MAX_TURNS) -> None:
        self._turns: dict[str, deque[Turn]] = defaultdict(lambda: deque(maxlen=max_turns))

    def add(self, conversation_id: str, turn: Turn) -> None:
        self._turns[conversation_id].append(turn)

    def history(self, conversation_id: str) -> list[Turn]:
        return list(self._turns.get(conversation_id, ()))

    def as_prompt(self, conversation_id: str, *, limit: int = 3) -> str:
        """Recent turns, formatted for the planner.

        Answers are truncated: the planner needs to know what was already discussed so
        it can resolve "it" and "that pump", not to re-read entire previous answers.
        """
        turns = self.history(conversation_id)[-limit:]
        if not turns:
            return ""
        lines = ["## Earlier in this conversation"]
        for turn in turns:
            lines.append(f"- Asked: {turn.question}")
            summary = turn.answer.strip().replace("\n", " ")
            lines.append(f"  Answered: {summary[:200]}{'…' if len(summary) > 200 else ''}")
        return "\n".join(lines)

    def clear(self, conversation_id: str) -> None:
        self._turns.pop(conversation_id, None)
