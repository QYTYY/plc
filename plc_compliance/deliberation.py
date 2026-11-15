"""Parallel three-round role deliberation for an assessment case."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import json
import time
from typing import Protocol

from plc_compliance.domain.models import AgentOpinion, Assessment, BaselineRule, Evidence, RuleFinding


ROLES = ("evidence_analyst", "baseline_expert", "risk_analyst")


class RoleReviewer(Protocol):
    def __call__(self, role: str, task: str, evidence: list[Evidence], rules: list[BaselineRule],
                 references: list[AgentOpinion], round_number: int) -> AgentOpinion: ...


@dataclass
class DeliberationResult:
    rounds: dict[int, list[AgentOpinion]]
    assessment: Assessment


class DeliberationRecorder:
    """Append every round and final assessment to an auditable JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, case_id: str, round_number: int, opinions: list[AgentOpinion]) -> None:
        self._append({"event": "round", "case_id": case_id, "round_number": round_number,
                      "opinions": [item.model_dump(mode="json") for item in opinions]})

    def record_final(self, result: DeliberationResult) -> None:
        self._append({"event": "final", "case_id": result.assessment.case_id,
                      "assessment": result.assessment.model_dump(mode="json")})

    def _append(self, payload: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class ParallelDeliberation:
    """Run each discussion round concurrently, with a barrier between rounds."""

    def __init__(self, reviewers: dict[str, RoleReviewer], *, max_workers: int = 3,
                 timeout_seconds: float = 90.0, max_attempts: int = 3,
                 recorder: DeliberationRecorder | None = None) -> None:
        missing = set(ROLES) - set(reviewers)
        if missing:
            raise ValueError(f"Missing reviewers for roles: {sorted(missing)}")
        self.reviewers = reviewers
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.recorder = recorder

    def run(self, *, task: str, evidence: list[Evidence], rules: list[BaselineRule],
            rule_findings: list[RuleFinding], case_id: str = "case") -> DeliberationResult:
        rounds: dict[int, list[AgentOpinion]] = {}
        references: list[AgentOpinion] = []
        for round_number in (1, 2, 3):
            opinions = self._run_round(case_id, round_number, task, evidence, rules, references)
            rounds[round_number] = opinions
            references = opinions  # references are read-only context for the next barrier
        result = DeliberationResult(rounds=rounds, assessment=self._adjudicate(case_id, rule_findings, rounds[3]))
        if self.recorder:
            self.recorder.record_final(result)
        return result

    def _run_round(self, case_id: str, round_number: int, task: str, evidence: list[Evidence],
                   rules: list[BaselineRule], references: list[AgentOpinion]) -> list[AgentOpinion]:
        opinions: list[AgentOpinion] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._call_with_retry, role, task, evidence, rules, references, round_number): role
                for role in ROLES
            }
            try:
                completed = as_completed(futures, timeout=self.timeout_seconds)
                for future in completed:
                    role = futures[future]
                    opinion = future.result()
                    if opinion.role != role or opinion.round_number != round_number:
                        raise ValueError(f"Reviewer returned invalid identity for {role}")
                    opinions.append(opinion)
            except TimeoutError as exc:
                for future in futures:
                    future.cancel()
                raise TimeoutError(f"第{round_number}轮评审超过 {self.timeout_seconds} 秒") from exc
        ordered = [next(item for item in opinions if item.role == role) for role in ROLES]
        if self.recorder:
            self.recorder.record(case_id=case_id, round_number=round_number, opinions=ordered)
        return ordered

    def _call_with_retry(self, role: str, task: str, evidence: list[Evidence], rules: list[BaselineRule],
                         references: list[AgentOpinion], round_number: int) -> AgentOpinion:
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                return self.reviewers[role](role, task, evidence, rules, list(references), round_number)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts:
                    time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"角色 {role} 在 {self.max_attempts} 次尝试后仍失败") from last_error

    @staticmethod
    def _adjudicate(case_id: str, findings: list[RuleFinding], opinions: list[AgentOpinion]) -> Assessment:
        if any(item.result == "non_compliant" for item in findings):
            conclusion = "non_compliant"
        elif any(item.result == "insufficient_evidence" for item in findings) or any(item.conclusion == "insufficient_evidence" for item in opinions):
            conclusion = "insufficient_evidence"
        elif len({item.conclusion for item in opinions}) > 1:
            conclusion = "insufficient_evidence"
        else:
            conclusion = opinions[0].conclusion if opinions else "insufficient_evidence"
        risk = "high" if any(item.result == "non_compliant" for item in findings) else "unknown"
        confidence = sum(item.confidence for item in opinions) / len(opinions) if opinions else 0.0
        return Assessment(
            assessment_id=f"ASSESS-{case_id}", case_id=case_id, conclusion=conclusion,
            risk_level=risk, confidence=confidence, rule_findings=findings,
            final_opinions=opinions, needs_human_review=conclusion != "compliant" or len({item.conclusion for item in opinions}) > 1,
        )


def make_rule_backed_reviewer(rule_findings: list[RuleFinding]) -> RoleReviewer:
    """Create an offline reviewer for integration tests and local smoke runs."""
    def review(role: str, task: str, evidence: list[Evidence], rules: list[BaselineRule],
               references: list[AgentOpinion], round_number: int) -> AgentOpinion:
        del task, evidence, rules
        if any(item.result == "non_compliant" for item in rule_findings):
            conclusion = "non_compliant"
        elif any(item.result == "insufficient_evidence" for item in rule_findings):
            conclusion = "insufficient_evidence"
        else:
            conclusion = "compliant"
        previous = next((item for item in references if item.role == role), None)
        return AgentOpinion(
            role=role, round_number=round_number, conclusion=conclusion, confidence=0.8,
            reasoning="基于确定性规则结果进行角色复核。", evidence_ids=[x for item in rule_findings for x in item.evidence_ids],
            rule_ids=[item.rule_id for item in rule_findings], reference_opinion_roles=[item.role for item in references],
            decision_changed=previous is not None and previous.conclusion != conclusion,
            change_reason="确定性规则结果发生变化" if previous is not None and previous.conclusion != conclusion else None,
        )
    return review
