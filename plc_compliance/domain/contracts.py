"""Replaceable boundaries used by later modules."""

from __future__ import annotations

from typing import Protocol

from plc_compliance.domain.models import BaselineRule, Evidence, RawInput, RuleFinding


class EvidenceExtractor(Protocol):
    """Extract traceable evidence from one raw input."""

    def extract(self, raw_input: RawInput) -> list[Evidence]:
        """Return atomic evidence items."""


class BaselineResolver(Protocol):
    """Resolve applicable versioned baseline items."""

    def resolve(self, query: str, *, version: str | None = None) -> list[BaselineRule]:
        """Return rules applicable to a task and context."""


class RuleEvaluator(Protocol):
    """Evaluate structured evidence against baseline constraints."""

    def evaluate(self, evidence: list[Evidence], rules: list[BaselineRule]) -> list[RuleFinding]:
        """Return auditable findings."""
