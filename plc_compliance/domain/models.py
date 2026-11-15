"""Versioned data contracts shared by every application module."""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

RawContent = str | list[dict[str, object]]


class Project(BaseModel):
    """A tenant-owned assessment project."""

    project_id: str
    name: str
    asset_type: str | None = None
    baseline_versions: list[str] = Field(default_factory=list)


class RawInput(BaseModel):
    """One uploaded multimodal artifact or message."""

    input_id: str
    source: str
    content: RawContent
    media_type: str
    content_hash: str | None = None


class Evidence(BaseModel):
    """An atomic, traceable fact extracted from a raw artifact."""

    evidence_id: str
    source: str
    location: str
    content: str
    evidence_type: str
    confidence: float = Field(ge=0, le=1)
    source_input_id: str | None = None
    extraction_method: str | None = None
    verified_by_human: bool = False


class CaseDossier(BaseModel):
    """Normalized case package passed to knowledge and assessment modules."""

    case_id: str | None = None
    case_summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class BaselineRule(BaseModel):
    """A versioned baseline item with semantic and executable information."""

    rule_id: str
    version: str
    requirement: str
    risk_level: Literal["low", "medium", "high", "critical"]
    safety_intent: str | None = None
    applicable_assets: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    constraint: dict[str, object] = Field(default_factory=dict)


class RuleFinding(BaseModel):
    """Auditable result from one deterministic rule execution."""

    rule_id: str
    result: Literal["compliant", "non_compliant", "insufficient_evidence", "not_applicable"]
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)
    actual_value: str | int | float | bool | None = None
    expected_value: str | int | float | bool | None = None


class AgentOpinion(BaseModel):
    """One role's structured opinion in one discussion round."""

    role: str
    round_number: int = Field(default=1, ge=1, le=3)
    conclusion: Literal["compliant", "non_compliant", "insufficient_evidence"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reference_opinion_roles: list[str] = Field(default_factory=list)
    decision_changed: bool = False
    change_reason: str | None = None


class Assessment(BaseModel):
    """Final auditable decision for one assessment case."""

    assessment_id: str
    case_id: str
    conclusion: Literal["compliant", "non_compliant", "insufficient_evidence", "not_applicable"]
    risk_level: Literal["low", "medium", "high", "critical", "unknown"]
    confidence: float = Field(ge=0, le=1)
    rule_findings: list[RuleFinding] = Field(default_factory=list)
    final_opinions: list[AgentOpinion] = Field(default_factory=list)
    needs_human_review: bool = False


class Report(BaseModel):
    """Structured report payload before DOCX/PDF rendering."""

    report_id: str
    title: str
    conclusion: str
    risk_level: str
    executive_summary: str
    findings: list[RuleFinding] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    assessment_id: str | None = None
    needs_human_review: bool = False
    discussion_rounds: dict[int, list[AgentOpinion]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Feedback(BaseModel):
    """Expert correction retained for controlled system evolution."""

    feedback_id: str
    assessment_id: str
    old_conclusion: str
    new_conclusion: str
    reason: str
    expert_id: str
    affected_rule_ids: list[str] = Field(default_factory=list)


class AssessmentState(TypedDict, total=False):
    """State passed through the LangGraph workflow."""

    case_id: str
    project: Project
    task: str
    raw_inputs: list[RawInput]
    case_summary: str
    evidence: list[Evidence]
    rules: list[BaselineRule]
    missing_evidence: list[str]
    conflicts: list[str]
    round1_opinions: Annotated[list[AgentOpinion], operator.add]
    round2_opinions: Annotated[list[AgentOpinion], operator.add]
    round3_opinions: Annotated[list[AgentOpinion], operator.add]
    deterministic_findings: list[str]
    rule_findings: list[RuleFinding]
    knowledge_snapshot: dict[str, str]
    final_conclusion: str
    needs_human_review: bool
    assessment: Assessment
    report: Report
    report_path: str
    feedback: Feedback
