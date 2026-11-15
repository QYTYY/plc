"""Candidate structured-rule extraction from normative text."""

from __future__ import annotations

import re

from plc_compliance.domain.models import BaselineRule
from plc_compliance.knowledge.models import KnowledgeChunk


class CandidateRuleExtractor:
    """Extract reviewable candidates; output must be approved before production use."""

    _MIN_LENGTH = re.compile(r"(?:密码|password).{0,40}?(?:不少于|至少|minimum(?:\s+length)?|at\s+least).{0,12}(\d+)", re.I)
    _PATTERNS = (
        ("default_password_disabled", re.compile(r"(?:默认|default).{0,20}(?:密码|password).{0,30}(?:修改|更改|禁用|disable|change)", re.I),
         "不得使用默认密码，首次使用或配置变更时应修改。", "high", "降低默认凭据被利用的风险", "configuration", {"field": "default_password_disabled", "operator": "==", "expected": True}),
        ("insecure_protocol_disabled", re.compile(r"(?:HTTP|FTP|Telnet).{0,40}(?:禁止|禁用|严禁|不得|不应|forbid|disable|avoid)", re.I),
         "应禁用或限制 HTTP、FTP、Telnet 等高风险明文协议。", "high", "降低明文传输和远程攻击风险", "configuration", {"field": "insecure_protocols_disabled", "operator": "contains", "expected": ["HTTP", "FTP", "Telnet"]}),
        ("asset_inventory", re.compile(r"(?:资产清单|资产列表|asset inventory|inventory of assets)", re.I),
         "应建立并维护工业控制系统资产清单。", "medium", "确保安全评估覆盖全部资产", "asset_inventory", {"field": "asset_inventory_present", "operator": "==", "expected": True}),
        ("multi_factor_authentication", re.compile(r"(?:多因素认证|多重身份认证|multi[- ]factor authentication|MFA)", re.I),
         "关键设备、系统或平台访问应采用多因素认证。", "high", "降低账号被盗用风险", "configuration", {"field": "mfa_enabled", "operator": "==", "expected": True}),
    )

    def extract(self, chunks: list[KnowledgeChunk], *, version: str = "candidate") -> list[BaselineRule]:
        rules: list[BaselineRule] = []
        seen: set[str] = set()
        for chunk in chunks:
            match = self._MIN_LENGTH.search(chunk.content)
            if match:
                expected = int(match.group(1))
                rule = BaselineRule(
                    rule_id=f"CANDIDATE-PWD-MIN-{expected}",
                    version=version,
                    requirement=chunk.content,
                    risk_level="high",
                    safety_intent="降低密码暴力破解风险",
                    required_evidence_types=["configuration", "command_output"],
                    constraint={"field": "password_min_length", "operator": ">=", "expected": expected},
                )
                if rule.rule_id not in seen:
                    rules.append(rule)
                    seen.add(rule.rule_id)
            for suffix, pattern, requirement, risk, intent, evidence_type, constraint in self._PATTERNS:
                if pattern.search(chunk.content):
                    rule = BaselineRule(
                        rule_id=f"CANDIDATE-{suffix.upper()}", version=version,
                        requirement=requirement, risk_level=risk, safety_intent=intent,
                        required_evidence_types=[evidence_type], constraint=constraint,
                    )
                    if rule.rule_id not in seen:
                        rules.append(rule)
                        seen.add(rule.rule_id)
        return rules
