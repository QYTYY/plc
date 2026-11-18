"""本地用户、项目、案件和人工审核管理入口。"""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plc_compliance.management.application import AssessmentApplication, encode


def parser() -> argparse.ArgumentParser:
    """Build the local management command interface."""
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument('--data', default=str(Path(__file__).resolve().parents[1] / 'knowledge_db/management'))
    root.add_argument('--user', help='操作人的登录用户名')
    commands = root.add_subparsers(dest='action', required=True)
    commands.add_parser('init-user', help='创建首个管理员').add_argument('username')
    commands.add_parser('create-user', help='管理员创建普通用户').add_argument('username')
    commands.add_parser('create-project', help='创建项目').add_argument('name')
    member = commands.add_parser('add-member', help='添加项目成员')
    member.add_argument('project_id')
    member.add_argument('user_id')
    member.add_argument('role', choices=['member', 'expert', 'rule_admin'])
    create = commands.add_parser('create-case', help='从案件JSON创建案件')
    create.add_argument('project_id')
    create.add_argument('input', type=Path)
    for name in ('run', 'recover', 'status'):
        command = commands.add_parser(name)
        command.add_argument('case_id')
        if name in {'run', 'recover'}:
            command.add_argument('--offline', action='store_true', help='离线测试；不调用大模型')
        if name == 'recover':
            command.add_argument('--confirm-stopped', action='store_true', required=True,
                                 help='确认原运行进程已停止，防止同时执行')
    commands.add_parser('list-cases').add_argument('project_id')
    publish = commands.add_parser('publish-rule', help='审核发布不可覆盖的正式规则版本')
    publish.add_argument('project_id')
    publish.add_argument('input', type=Path, help='单条 BaselineRule JSON 文件')
    review = commands.add_parser('review', help='专家填写结论和原因，恢复案件')
    review.add_argument('case_id')
    review.add_argument('--conclusion', required=True, choices=['合规', '不合规', '证据不足', '不适用'])
    review.add_argument('--reason', required=True)
    review.add_argument('--confirm', nargs='*', default=[], help='已人工确认的证据编号')
    commands.add_parser('audit', help='管理员查询审计日志')
    return root


def dispatch(application: AssessmentApplication, args: argparse.Namespace, token: str) -> object:
    """Route authenticated local operations to the application service."""
    if args.action == 'create-user':
        return application.access.create_user(args.username, getpass.getpass('新用户密码：'), token=token)
    if args.action == 'create-project':
        return application.access.create_project(token, args.name)
    if args.action == 'add-member':
        application.access.add_member(token, args.project_id, args.user_id, args.role)
        return '项目成员已更新。'
    if args.action == 'create-case':
        return application.create_case(token, args.project_id, json.loads(args.input.read_text(encoding='utf-8')))
    if args.action == 'run':
        return application.run(token, args.case_id)
    if args.action == 'recover':
        return application.recover(token, args.case_id, worker_stopped=args.confirm_stopped)
    if args.action == 'status':
        return application.get_case(token, args.case_id)
    if args.action == 'list-cases':
        return application.list_cases(token, args.project_id)
    if args.action == 'publish-rule':
        from plc_compliance.domain.models import BaselineRule
        rule = BaselineRule.model_validate_json(args.input.read_text(encoding='utf-8'))
        application.publish_rule(token, args.project_id, rule)
        return '正式规则版本已发布。'
    if args.action == 'review':
        conclusion = {'合规': 'compliant', '不合规': 'non_compliant', '证据不足': 'insufficient_evidence', '不适用': 'not_applicable'}[args.conclusion]
        return application.review(token, args.case_id, conclusion=conclusion,
                                  reason=args.reason, confirmed_evidence_ids=args.confirm)
    return application.audit_log(token)


def main() -> None:
    """Prompt for credentials without placing passwords in shell history."""
    args = parser().parse_args()
    options = {}
    if args.action in {'run', 'recover'} and not args.offline:
        from plc_compliance.deepseek import create_deepseek_model
        options['model'] = create_deepseek_model()
        database = Path(__file__).resolve().parents[1] / 'knowledge_db/chroma'
        manifest = database / 'index_manifest.json'
        if manifest.is_file():
            from plc_compliance.knowledge.embeddings import FastEmbedProvider
            from plc_compliance.knowledge.service import KnowledgeService
            from plc_compliance.knowledge.vectorstore import ChromaVectorStore
            metadata = json.loads(manifest.read_text(encoding='utf-8'))
            options['knowledge_service'] = KnowledgeService(
                embeddings=FastEmbedProvider(metadata['embedding_model']),
                vector_store=ChromaVectorStore(str(database)),
            )
        else:
            raise FileNotFoundError('未找到知识库索引，请先运行 scripts/build_knowledge_index.py。')
    with AssessmentApplication(args.data, **options) as application:
        if args.action == 'init-user':
            with application.store.transaction() as connection:
                if connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                    raise PermissionError('已有管理员，请使用 create-user。')
            print('管理员编号：', application.access.create_user(args.username, getpass.getpass('管理员密码：')))
            return
        username = args.user or input('登录用户名：')
        token = application.access.login(username, getpass.getpass('登录密码：'))
        try:
            print(encode(dispatch(application, args, token)))
        finally:
            application.access.logout(token)


if __name__ == '__main__':
    main()
