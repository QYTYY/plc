"""Controlled expert-feedback boundary for later knowledge evolution."""

from __future__ import annotations

from typing import Protocol

from plc_compliance.models import Feedback


class FeedbackRepository(Protocol):
    """Store feedback without silently changing production rules."""

    def save(self, feedback: Feedback) -> None:
        """Persist one expert correction."""


class InMemoryFeedbackRepository:
    """Development repository; production should use a database."""

    def __init__(self) -> None:
        self.items: list[Feedback] = []

    def save(self, feedback: Feedback) -> None:
        self.items.append(feedback)
