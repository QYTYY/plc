"""Validated expert review decisions."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ReviewDecision(BaseModel):
    """An explicit, attributable correction which never edits production rules."""

    conclusion: Literal['compliant', 'non_compliant', 'insufficient_evidence', 'not_applicable']
    reason: str = Field(min_length=1)
    expert_id: str
    confirmed_evidence_ids: list[str] = Field(default_factory=list)

    @field_validator('reason')
    @classmethod
    def require_reason(cls, value: str) -> str:
        """Reject whitespace-only explanations."""
        if not value.strip():
            raise ValueError('请填写人工复核原因。')
        return value.strip()
