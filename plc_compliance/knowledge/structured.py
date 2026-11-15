"""Structured baseline rules kept alongside semantic knowledge chunks."""

from __future__ import annotations

from plc_compliance.domain.models import BaselineRule


class BaselineKnowledgeStore:
    """In-memory versioned baseline store used by the application graph."""

    def __init__(self, rules: list[BaselineRule] | None = None) -> None:
        self._rules = rules or []

    def add(self, rule: BaselineRule) -> None:
        self._rules.append(rule)

    def resolve(self, query: str, *, version: str | None = None) -> list[BaselineRule]:
        terms = query.lower().split()
        return [
            rule
            for rule in self._rules
            if (version is None or rule.version == version)
            and any(term in rule.requirement.lower() or term in (rule.safety_intent or "").lower() for term in terms)
        ]


InMemoryBaselineKnowledgeStore = BaselineKnowledgeStore
