"""Persistent assessment application with project isolation and expert review."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command
from pydantic import BaseModel, TypeAdapter

from plc_compliance.domain.models import AssessmentState, BaselineRule
from plc_compliance.graph import build_assessment_graph
from plc_compliance.management.access import AccessService
from plc_compliance.management.review import ReviewDecision
from plc_compliance.management.store import SQLiteStore, utcnow


def encode(value: object) -> str:
    """Serialize domain models without credentials or Python object encodings."""
    return json.dumps(value, ensure_ascii=False, default=lambda item: item.model_dump(mode='json')
                      if isinstance(item, BaseModel) else str(item))


class AssessmentApplication:
    """Own SQLite connections for the lifetime of a local application instance."""

    def __init__(self, directory: str | Path = 'knowledge_db/management', **graph_options: object) -> None:
        self.directory = Path(directory).resolve()
        self.store = SQLiteStore(self.directory / 'business.sqlite')
        self.access = AccessService(self.store)
        self.connection = sqlite3.connect(self.directory / 'checkpoints.sqlite', check_same_thread=False)
        allowed_types = [("plc_compliance.domain.models", name) for name in (
            'Project', 'RawInput', 'Evidence', 'BaselineRule', 'RuleFinding',
            'AgentOpinion', 'Assessment', 'Report', 'Feedback')]
        self.checkpointer = SqliteSaver(self.connection, serde=JsonPlusSerializer(
            allowed_msgpack_modules=allowed_types,
        ))
        self.graph = build_assessment_graph(
            **graph_options, checkpointer=self.checkpointer, human_review=True,
            recorder_path=self.directory / 'discussion.jsonl', report_dir=self.directory / 'reports',
        )

    def __enter__(self) -> 'AssessmentApplication':
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the checkpoint connection after all graph work finishes."""
        self.connection.close()

    def create_case(self, token: str, project_id: str, state: dict) -> str:
        """Register inputs with a generated case/thread identity scoped to the project."""
        actor = self.access.require(token, project_id)
        case_id = uuid4().hex
        allowed = {key: value for key, value in state.items() if key in {
            'task', 'raw_inputs', 'evidence', 'rules', 'case_summary', 'missing_evidence', 'conflicts'}}
        if not str(allowed.get('task', '')).strip():
            raise ValueError('案件必须包含评估任务。')
        if allowed.get('rules'):
            self.access.require(token, project_id, {'owner', 'rule_admin'})
        allowed['case_id'] = case_id
        if not allowed.get('rules'):
            with self.store.transaction() as connection:
                versions = connection.execute('SELECT rule_id,payload FROM rule_versions WHERE project_id=? ORDER BY rowid',
                                              (project_id,)).fetchall()
            latest = {row['rule_id']: json.loads(row['payload']) for row in versions}
            allowed['rules'] = list(latest.values())
        validated = TypeAdapter(AssessmentState).validate_python(allowed)
        with self.store.transaction() as connection:
            connection.execute('INSERT INTO cases VALUES(?,?,?,?,?)',
                               (case_id, project_id, f'{project_id}:{case_id}', 'created', encode(validated)))
            self.store.audit(connection, actor, 'create_case', case_id, {'project_id': project_id})
        return case_id

    def get_case(self, token: str, case_id: str) -> dict:
        """Read a case only after checking its project membership."""
        with self.store.transaction() as connection:
            row = connection.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone()
        if row is None:
            raise LookupError('案件不存在。')
        self.access.require(token, row['project_id'])
        return {**dict(row), 'state': json.loads(row['state'])}

    def _claim(self, token: str, case_id: str, statuses: tuple[str, ...]) -> dict:
        case = self.get_case(token, case_id)
        actor = self.access.require(token, case['project_id'])
        placeholders = ','.join('?' for _ in statuses)
        with self.store.transaction() as connection:
            changed = connection.execute(
                f'UPDATE cases SET status=? WHERE id=? AND status IN ({placeholders})',
                ('running', case_id, *statuses),
            ).rowcount
            if not changed:
                raise ValueError('案件正在运行或当前状态不支持此操作。')
            self.store.audit(connection, actor, 'run_case', case_id)
        return case

    def run(self, token: str, case_id: str) -> dict:
        """Start a new case or recover a failed case from its last checkpoint."""
        case = self._claim(token, case_id, ('created', 'failed'))
        config = {'configurable': {'thread_id': case['thread_id']}}
        snapshot = self.graph.get_state(config)
        incoming = None if snapshot.values else TypeAdapter(AssessmentState).validate_python(case['state'])
        return self._execute(case, incoming)

    def _execute(self, case: dict, incoming: object) -> dict:
        config = {'configurable': {'thread_id': case['thread_id']}}
        try:
            self.graph.invoke(incoming, config)
        except Exception:
            self._save_snapshot(case, 'failed')
            raise
        snapshot = self.graph.get_state(config)
        self._save_snapshot(case, 'awaiting_review' if snapshot.next else 'completed')
        return {'status': 'awaiting_review' if snapshot.next else 'completed', 'state': snapshot.values}

    def _save_snapshot(self, case: dict, status: str) -> None:
        snapshot = self.graph.get_state({'configurable': {'thread_id': case['thread_id']}})
        with self.store.transaction() as connection:
            if snapshot.values:
                connection.execute('UPDATE cases SET status=?,state=? WHERE id=?',
                                   (status, encode(snapshot.values), case['id']))
            else:
                connection.execute('UPDATE cases SET status=? WHERE id=?', (status, case['id']))
            self.store.audit(connection, 'workflow', status, case['id'])

    def review(self, token: str, case_id: str, *, conclusion: str, reason: str,
               confirmed_evidence_ids: list[str] | None = None) -> dict:
        """Persist expert feedback before resuming a paused assessment."""
        case = self.get_case(token, case_id)
        actor = self.access.require(token, case['project_id'], {'owner', 'expert'})
        decision = ReviewDecision(conclusion=conclusion, reason=reason, expert_id=actor,
                                  confirmed_evidence_ids=confirmed_evidence_ids or [])
        valid_ids = {item['evidence_id'] for item in case['state'].get('evidence', [])}
        if set(decision.confirmed_evidence_ids) - valid_ids:
            raise ValueError('复核证据编号不属于当前案件。')
        with self.store.transaction() as connection:
            changed = connection.execute('UPDATE cases SET status=? WHERE id=? AND status=?',
                                         ('running', case_id, 'awaiting_review')).rowcount
            if not changed:
                raise ValueError('案件当前不处于等待审核状态。')
            feedback = {**decision.model_dump(), 'old_conclusion': case['state'].get('final_conclusion')}
            connection.execute('INSERT INTO feedback VALUES(?,?,?,?,?)',
                               (uuid4().hex, case_id, actor, encode(feedback), utcnow()))
            self.store.audit(connection, actor, 'review_case', case_id, feedback)
        return self._execute(case, Command(resume=decision.model_dump()))

    def recover(self, token: str, case_id: str, *, worker_stopped: bool = False) -> dict:
        """Explicitly reclaim a task left running after process termination."""
        if not worker_stopped:
            raise ValueError('请先确认原运行进程已经停止，再恢复案件。')
        case = self.get_case(token, case_id)
        actor = self.access.require(token, case['project_id'], {'owner'})
        with self.store.transaction() as connection:
            if case['status'] != 'running':
                raise ValueError('只有异常中断且仍标记为运行中的案件需要此操作。')
            changed = connection.execute('UPDATE cases SET status=? WHERE id=? AND status=?',
                                         ('failed', case_id, 'running')).rowcount
            if not changed:
                raise ValueError('案件状态已改变，请重新查询。')
            self.store.audit(connection, actor, 'recover_case', case_id)
        return self.run(token, case_id)

    def list_cases(self, token: str, project_id: str) -> list[dict]:
        """List only cases within an authorized project."""
        self.access.require(token, project_id)
        with self.store.transaction() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT id,status FROM cases WHERE project_id=?', (project_id,))]

    def publish_rule(self, token: str, project_id: str, rule: BaselineRule) -> None:
        """Publish an immutable rule version with reviewer provenance."""
        actor = self.access.require(token, project_id, {'owner', 'rule_admin'})
        if not rule.constraint.get('field') or not rule.constraint.get('operator') or 'expected' not in rule.constraint:
            raise ValueError('正式规则必须包含完整的可执行约束。')
        with self.store.transaction() as connection:
            connection.execute('INSERT INTO rule_versions VALUES(?,?,?,?)',
                               (project_id, rule.rule_id, rule.version, rule.model_dump_json()))
            self.store.audit(connection, actor, 'publish_rule', project_id,
                             {'rule_id': rule.rule_id, 'version': rule.version})

    def audit_log(self, token: str) -> list[dict]:
        """Expose system-wide audit events to administrators only."""
        self.access.authenticate(token, admin=True)
        with self.store.transaction() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM audit ORDER BY id')]
