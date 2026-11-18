"""Behavior tests for durable review, isolation, authorization and recovery."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plc_compliance.domain.models import BaselineRule
from plc_compliance.management.application import AssessmentApplication


def case_state(value: str = 'false', *, low_confidence: bool = False) -> dict:
    return {'task': '检查多因素认证', 'evidence': [{
        'evidence_id': 'E1', 'source': 'config.txt', 'location': 'line_1',
        'content': f'mfa_enabled={value}', 'evidence_type': 'configuration',
        'confidence': 0.4 if low_confidence else 1.0, 'needs_human_review': low_confidence,
    }], 'rules': [{
        'rule_id': 'MFA', 'version': 'v1', 'requirement': '应启用多因素认证', 'risk_level': 'high',
        'constraint': {'field': 'mfa_enabled', 'operator': '==', 'expected': True},
    }]}


class ManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.app = AssessmentApplication(self.directory)
        self.app.access.create_user('admin', 'admin-password-123')
        self.token = self.app.access.login('admin', 'admin-password-123')
        self.project = self.app.access.create_project(self.token, 'PLC项目')

    def tearDown(self) -> None:
        self.app.close()
        self.temp.cleanup()

    def user(self, name: str) -> tuple[str, str]:
        identifier = self.app.access.create_user(name, 'member-password-123', token=self.token)
        return identifier, self.app.access.login(name, 'member-password-123')

    def test_restart_resume_preserves_rounds_and_feedback(self) -> None:
        case = self.app.create_case(self.token, self.project, case_state())
        self.assertEqual(self.app.run(self.token, case)['status'], 'awaiting_review')
        self.assertFalse(list((self.directory / 'reports').glob('*.json')))
        self.app.close()
        self.app = AssessmentApplication(self.directory)
        result = self.app.review(self.token, case, conclusion='non_compliant', reason='已核实配置。')
        self.assertEqual(result['status'], 'completed')
        for number in (1, 2, 3):
            self.assertEqual(len(result['state'][f'round{number}_opinions']), 3)
        report = json.loads(Path(result['state']['report_path']).read_text(encoding='utf-8'))
        self.assertEqual(report['expert_review']['reason'], '已核实配置。')
        with self.app.store.transaction() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.app.run(self.token, case)

    def test_cross_project_and_review_permissions(self) -> None:
        member, member_token = self.user('member')
        _, outsider_token = self.user('outsider')
        self.app.access.add_member(self.token, self.project, member, 'member')
        self.app.publish_rule(self.token, self.project, BaselineRule.model_validate(case_state()['rules'][0]))
        state = case_state()
        state.pop('rules')
        case = self.app.create_case(member_token, self.project, state)
        self.app.run(member_token, case)
        with self.assertRaises(PermissionError):
            self.app.get_case(outsider_token, case)
        with self.assertRaises(PermissionError):
            self.app.review(member_token, case, conclusion='compliant', reason='越权')
        with self.assertRaises(PermissionError):
            self.app.access.add_member(member_token, self.project, member, 'expert')
        self.app.access.add_member(self.token, self.project, member, 'expert')
        self.assertEqual(self.app.review(member_token, case, conclusion='non_compliant', reason='复核完成')['status'], 'completed')

    def test_session_revocation_and_no_plaintext_credentials(self) -> None:
        _, token = self.user('session-user')
        self.app.access.logout(token)
        with self.assertRaises(PermissionError):
            self.app.access.authenticate(token)
        with self.assertRaises(PermissionError):
            self.app.access.login('admin', 'wrong-password')
        with self.app.store.transaction() as connection:
            data = str([tuple(row) for row in connection.execute('SELECT * FROM users')])
        self.assertNotIn('admin-password-123', data)
        self.assertNotIn(self.token, str(self.app.audit_log(self.token)))

    def test_low_confidence_requires_explicit_evidence_confirmation(self) -> None:
        case = self.app.create_case(self.token, self.project, case_state('true', low_confidence=True))
        self.assertEqual(self.app.run(self.token, case)['status'], 'awaiting_review')
        with self.assertRaises(ValueError):
            self.app.review(self.token, case, conclusion='compliant', reason=' ', confirmed_evidence_ids=['E1'])
        with self.assertRaises(ValueError):
            self.app.review(self.token, case, conclusion='compliant', reason='已核实', confirmed_evidence_ids=['OTHER'])
        result = self.app.review(self.token, case, conclusion='compliant', reason='对照原图确认。', confirmed_evidence_ids=['E1'])
        self.assertFalse(result['state']['needs_human_review'])
        self.assertTrue(result['state']['evidence'][0].verified_by_human)

    def test_failed_report_can_resume_without_repeating_deliberation(self) -> None:
        case = self.app.create_case(self.token, self.project, case_state('true'))
        with patch('plc_compliance.graph.save_report', side_effect=OSError('模拟写入失败')):
            with self.assertRaises(OSError):
                self.app.run(self.token, case)
        self.assertEqual(self.app.get_case(self.token, case)['status'], 'failed')
        result = self.app.run(self.token, case)
        self.assertEqual(result['status'], 'completed')
        events = (self.directory / 'discussion.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(events), 4)

    def test_published_rule_versions_are_immutable_and_loaded_into_case(self) -> None:
        rule = BaselineRule.model_validate(case_state()['rules'][0])
        self.app.publish_rule(self.token, self.project, rule)
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.publish_rule(self.token, self.project, rule)
        case = self.app.create_case(self.token, self.project, {'task': '从正式库加载规则'})
        self.assertEqual(self.app.get_case(self.token, case)['state']['rules'][0]['rule_id'], 'MFA')

    def test_running_case_requires_explicit_recovery_and_cannot_run_twice(self) -> None:
        case = self.app.create_case(self.token, self.project, case_state('true'))
        with self.app.store.transaction() as connection:
            connection.execute('UPDATE cases SET status=? WHERE id=?', ('running', case))
        with self.assertRaises(ValueError):
            self.app.run(self.token, case)
        with self.assertRaises(ValueError):
            self.app.recover(self.token, case)
        self.assertEqual(self.app.recover(self.token, case, worker_stopped=True)['status'], 'completed')

    def test_expired_session_and_member_cannot_publish_rules(self) -> None:
        member, token = self.user('limited')
        self.app.access.add_member(self.token, self.project, member, 'member')
        with self.assertRaises(PermissionError):
            self.app.create_case(token, self.project, case_state())
        with self.assertRaises(PermissionError):
            self.app.publish_rule(token, self.project, BaselineRule.model_validate(case_state()['rules'][0]))
        with self.app.store.transaction() as connection:
            connection.execute('UPDATE sessions SET expires=0 WHERE user_id=?', (member,))
        with self.assertRaises(PermissionError):
            self.app.access.authenticate(token)


if __name__ == '__main__':
    unittest.main()
