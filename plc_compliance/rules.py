"""Deterministic, auditable execution of approved baseline rules."""

from __future__ import annotations

import json
import re
from typing import Any

from plc_compliance.domain.models import BaselineRule, Evidence, RuleFinding


class RuleEngine:
    """Evaluate structured constraints without delegating decisions to an LLM."""

    def evaluate(self, evidence: list[Evidence], rules: list[BaselineRule]) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        for rule in rules:
            constraint = rule.constraint or {}
            field = str(constraint.get("field", ""))
            operator = str(constraint.get("operator", "=="))
            expected = constraint.get("expected")
            if not field:
                findings.append(RuleFinding(rule_id=rule.rule_id, result="insufficient_evidence", explanation="规则没有定义可执行字段。"))
                continue
            matches = [(item, value) for item in evidence for key, value in _extract_values(item.content).items() if key == field]
            if not matches:
                findings.append(RuleFinding(rule_id=rule.rule_id, result="insufficient_evidence", explanation=f"未在证据中找到字段 {field}。", expected_value=expected if _scalar(expected) else None))
                continue
            item, actual = matches[-1]
            passed = _compare(actual, operator, expected)
            findings.append(RuleFinding(
                rule_id=rule.rule_id,
                result="compliant" if passed else "non_compliant",
                explanation=f"字段 {field} 的实际值为 {actual!r}，期望条件为 {operator} {expected!r}。",
                evidence_ids=[item.evidence_id],
                actual_value=actual if _scalar(actual) else None,
                expected_value=expected if _scalar(expected) else None,
            ))
        return findings


def run_deterministic_rules(evidence: list[Evidence], rules: list[BaselineRule]) -> list[str]:
    """Compatibility helper returning human-readable findings."""
    return [f"{item.rule_id}: {item.explanation}" for item in RuleEngine().evaluate(evidence, rules)]


def _extract_values(content: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            values.update(parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    pattern = r'(?:^|[\s,;])([A-Za-z][A-Za-z0-9_.-]*)\s*[:=]\s*("[^"]*"|\'[^\']*\'|[^\s,;]+)'
    for match in re.finditer(pattern, content):
        key, raw = match.groups()
        values.setdefault(key, _parse_scalar(raw))
    return values


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    lowered = value.lower()
    if lowered in {"true", "yes", "enabled", "on"}:
        return True
    if lowered in {"false", "no", "disabled", "off"}:
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    try:
        if operator in {"==", "eq"}: return actual == expected
        if operator in {"!=", "ne"}: return actual != expected
        if operator in {">=", "ge"}: return actual >= expected
        if operator in {"<=", "le"}: return actual <= expected
        if operator in {">", "gt"}: return actual > expected
        if operator in {"<", "lt"}: return actual < expected
        if operator in {"contains", "in"}: return expected in actual if isinstance(actual, (list, str, tuple, set)) else False
        if operator == "contains_all": return all(item in actual for item in expected) if isinstance(actual, (list, str, tuple, set)) else False
    except (TypeError, ValueError):
        return False
    return False


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None
