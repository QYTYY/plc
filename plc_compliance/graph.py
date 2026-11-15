"""LangGraph entry point for the complete PLC assessment workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plc_compliance.deliberation import DeliberationRecorder, ParallelDeliberation, ROLES, make_rule_backed_reviewer
from plc_compliance.agents import build_case_dossier, build_intake_agent, make_harness_reviewer
from plc_compliance.ingestion import EvidenceIngestionService
from plc_compliance.knowledge import BaselineKnowledgeStore, InMemoryBaselineKnowledgeStore
from plc_compliance.models import AssessmentState
from plc_compliance.rag import PlaceholderRAG, RoleAwareRAG
from plc_compliance.reporting import build_report, save_report
from plc_compliance.rules import RuleEngine, run_deterministic_rules


def build_assessment_graph(model: Any = None, knowledge_store: BaselineKnowledgeStore | None = None,
                           knowledge_service: Any = None, recorder_path: str | Path = "knowledge_db/discussion.jsonl",
                           report_dir: str | Path = "knowledge_db/reports", timeout_seconds: float = 90.0,
                           max_attempts: int = 3):
    """Build the LangGraph workflow with RAG, deliberation, persistence and reporting.

    ``model`` can be a DeepSeek ChatOpenAI instance. When omitted, an offline
    rule-backed reviewer is used so the graph remains testable without an API.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("请安装 LangGraph 后再构建评估流程") from exc

    knowledge_store = knowledge_store or InMemoryBaselineKnowledgeStore()
    ingestion = EvidenceIngestionService()
    engine = RuleEngine()
    rag_by_role = {
        role: RoleAwareRAG(knowledge_service, role) if knowledge_service else PlaceholderRAG(role)
        for role in ROLES
    }
    recorder = DeliberationRecorder(recorder_path)

    intake_agent = build_intake_agent(model) if model is not None else None

    def intake_node(state: AssessmentState) -> dict[str, object]:
        raw_inputs = state.get("raw_inputs", [])
        if not raw_inputs:
            return {"case_summary": state.get("case_summary", "预处理证据已由调用方提供。")}
        evidence = ingestion.extract(raw_inputs)
        if intake_agent is not None:
            dossier = build_case_dossier(intake_agent, state.get("task", ""), raw_inputs)
            evidence = ingestion.merge(evidence, dossier.evidence)
            return {"case_summary": dossier.case_summary, "evidence": evidence,
                    "missing_evidence": dossier.missing_evidence, "conflicts": dossier.conflicts}
        return {"case_summary": f"已标准化 {len(evidence)} 条证据。", "evidence": evidence}

    def knowledge_node(state: AssessmentState) -> dict[str, object]:
        rules = state.get("rules", []) or knowledge_store.resolve(state.get("task", ""))
        return {"rules": rules, "knowledge_snapshot": {rule.rule_id: rule.version for rule in rules}}

    def deterministic_node(state: AssessmentState) -> dict[str, object]:
        findings = engine.evaluate(state.get("evidence", []), state.get("rules", []))
        return {"rule_findings": findings, "deterministic_findings": run_deterministic_rules(state.get("evidence", []), state.get("rules", []))}

    def deliberation_node(state: AssessmentState) -> dict[str, object]:
        findings = state.get("rule_findings", [])
        if model is None:
            reviewer = make_rule_backed_reviewer(findings)
            reviewers = {role: reviewer for role in ROLES}
        else:
            reviewer = make_harness_reviewer(model, rag_by_role)
            reviewers = {role: reviewer for role in ROLES}
        result = ParallelDeliberation(reviewers, recorder=recorder, timeout_seconds=timeout_seconds, max_attempts=max_attempts).run(
            task=state.get("task", ""), evidence=state.get("evidence", []), rules=state.get("rules", []),
            rule_findings=findings, case_id=state.get("case_id", "case"))
        return {
            "round1_opinions": result.rounds[1], "round2_opinions": result.rounds[2], "round3_opinions": result.rounds[3],
            "assessment": result.assessment, "final_conclusion": result.assessment.conclusion,
            "needs_human_review": result.assessment.needs_human_review,
        }

    def report_node(state: AssessmentState) -> dict[str, object]:
        report = build_report(state)
        path = save_report(report, Path(report_dir) / f"{report.report_id}.json")
        return {"report": report, "report_path": str(path)}

    graph = StateGraph(AssessmentState)
    graph.add_node("intake", intake_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("deterministic_rules", deterministic_node)
    graph.add_node("deliberation", deliberation_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "knowledge")
    graph.add_edge("knowledge", "deterministic_rules")
    graph.add_edge("deterministic_rules", "deliberation")
    graph.add_edge("deliberation", "report")
    graph.add_edge("report", END)
    return graph.compile()
