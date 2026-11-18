"""Report assembly separated from DOCX/PDF rendering."""

from __future__ import annotations

from uuid import uuid4
from pathlib import Path
import json

from plc_compliance.models import AssessmentState, Report

_CONCLUSION_ZH = {"compliant": "合规", "non_compliant": "不合规", "insufficient_evidence": "证据不足", "not_applicable": "不适用"}
_RISK_ZH = {"low": "低", "medium": "中", "high": "高", "critical": "严重", "unknown": "未知"}


def build_report(state: AssessmentState) -> Report:
    """Build a traceable structured report from final assessment state."""
    findings = state.get("rule_findings", [])
    evidence_ids = sorted({item for finding in findings for item in finding.evidence_ids})
    review_evidence_ids = sorted(item.evidence_id for item in state.get("evidence", []) if item.needs_human_review)
    conclusion = state.get("final_conclusion", "insufficient_evidence")
    risk_level = state['assessment'].risk_level if state.get('assessment') else 'unknown'
    return Report(
        report_id=f"RPT-{uuid4().hex[:10]}",
        title=f"工业控制系统安全评估报告：{state['case_id']}",
        conclusion=_CONCLUSION_ZH.get(conclusion, conclusion),
        risk_level=_RISK_ZH.get(risk_level, risk_level),
        executive_summary=state.get("case_summary", "暂无案件摘要。"),
        findings=findings,
        evidence_ids=evidence_ids,
        assessment_id=state.get("assessment").assessment_id if state.get("assessment") else None,
        needs_human_review=bool(state.get("needs_human_review", True)),
        human_review_evidence_ids=review_evidence_ids,
        expert_review=state.get('review_decision', {}),
        discussion_rounds={number: state.get(f"round{number}_opinions", []) for number in (1, 2, 3)},
    )


def save_report(report: Report, path: str | Path) -> Path:
    """Persist the auditable report as UTF-8 JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    for opinion in payload.get("discussion_rounds", {}).values():
        for item in opinion:
            item["conclusion"] = _CONCLUSION_ZH.get(item.get("conclusion", ""), item.get("conclusion", ""))
    for finding in payload.get("findings", []):
        finding["result"] = {"compliant": "合规", "non_compliant": "不合规", "insufficient_evidence": "证据不足", "not_applicable": "不适用"}.get(finding.get("result", ""), finding.get("result", ""))
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
