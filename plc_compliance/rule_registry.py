"""Review and persistence helpers for baseline rules."""

from __future__ import annotations

import json
from pathlib import Path

from plc_compliance.domain.models import BaselineRule


class BaselineRuleRegistry:
    """Store only explicitly approved rules for deterministic evaluation."""

    def __init__(self, rules: list[BaselineRule] | None = None) -> None:
        self.rules = rules or []

    @classmethod
    def load(cls, path: str | Path) -> "BaselineRuleRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([BaselineRule.model_validate(item) for item in data])

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps([rule.model_dump() for rule in self.rules], ensure_ascii=False, indent=2), encoding="utf-8")

    def approve_candidates(self, candidates: list[BaselineRule], rule_ids: set[str]) -> list[BaselineRule]:
        """Explicitly approve selected candidate IDs and return added rules."""
        added: list[BaselineRule] = []
        for candidate in candidates:
            if candidate.rule_id in rule_ids and all(item.rule_id != candidate.rule_id for item in self.rules):
                approved = candidate.model_copy(update={"version": f"approved-{candidate.version}"})
                self.rules.append(approved)
                added.append(approved)
        return added
