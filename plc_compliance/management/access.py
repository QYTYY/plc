"""Password authentication, expiring sessions and project authorization."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

from plc_compliance.management.store import SQLiteStore


def password_hash(password: str, salt: str | None = None) -> str:
    """Hash a password with a unique salt using PBKDF2 SHA-256."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000)
    return f'{salt}:{digest.hex()}'


class AccessService:
    """Use opaque session tokens rather than trusting caller-supplied user IDs."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def create_user(self, username: str, password: str, *, token: str | None = None) -> str:
        """Bootstrap the first admin; subsequent accounts require administrator login."""
        if not username.strip() or len(password) < 12:
            raise ValueError('用户名不能为空，密码至少需要12个字符。')
        with self.store.transaction() as connection:
            bootstrap = connection.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
            actor = 'bootstrap' if bootstrap else self.authenticate(token or '', admin=True)
            user_id = uuid4().hex
            connection.execute('INSERT INTO users VALUES(?,?,?,?)',
                               (user_id, username, password_hash(password), int(bootstrap)))
            self.store.audit(connection, actor, 'create_user', user_id)
        return user_id

    def login(self, username: str, password: str) -> str:
        """Issue a session valid for eight hours after password verification."""
        with self.store.transaction() as connection:
            row = connection.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            encoded = row['password'] if row else password_hash('dummy-password')
            valid = hmac.compare_digest(encoded, password_hash(password, encoded.split(':')[0]))
            if not row or not valid:
                raise PermissionError('用户名或密码错误。')
            token = secrets.token_urlsafe(32)
            connection.execute('INSERT INTO sessions VALUES(?,?,?)',
                               (hashlib.sha256(token.encode()).hexdigest(), row['id'], time.time() + 28800))
            self.store.audit(connection, row['id'], 'login', row['id'])
        return token

    def authenticate(self, token: str, *, admin: bool = False) -> str:
        """Validate an unexpired persistent session."""
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                'SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.digest=? AND s.expires>?',
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
        if not row or (admin and not row['admin']):
            raise PermissionError('未登录、登录已过期或没有管理员权限。')
        return row['id']

    def logout(self, token: str) -> None:
        """Revoke a session immediately."""
        actor = self.authenticate(token)
        with self.store.transaction() as connection:
            connection.execute('DELETE FROM sessions WHERE digest=?', (hashlib.sha256(token.encode()).hexdigest(),))
            self.store.audit(connection, actor, 'logout', actor)

    def require(self, token: str, project_id: str, roles: set[str] | None = None) -> str:
        """Enforce membership and an optional project role, including administrator override."""
        actor = self.authenticate(token)
        with self.store.transaction() as connection:
            user = connection.execute('SELECT admin FROM users WHERE id=?', (actor,)).fetchone()
            member = connection.execute('SELECT role FROM members WHERE project_id=? AND user_id=?',
                                        (project_id, actor)).fetchone()
        if not user['admin'] and (not member or (roles and member['role'] not in roles)):
            raise PermissionError('没有此项目的操作权限。')
        return actor

    def create_project(self, token: str, name: str) -> str:
        """Create a project owned by the authenticated user."""
        actor = self.authenticate(token)
        if not name.strip():
            raise ValueError('项目名称不能为空。')
        project_id = uuid4().hex
        with self.store.transaction() as connection:
            connection.execute('INSERT INTO projects VALUES(?,?)', (project_id, name))
            connection.execute('INSERT INTO members VALUES(?,?,?)', (project_id, actor, 'owner'))
            self.store.audit(connection, actor, 'create_project', project_id)
        return project_id

    def add_member(self, token: str, project_id: str, user_id: str, role: str) -> None:
        """Grant or update project membership through its owner."""
        actor = self.require(token, project_id, {'owner'})
        if role not in {'member', 'expert', 'rule_admin'}:
            raise ValueError('成员角色必须是 member、expert 或 rule_admin。')
        with self.store.transaction() as connection:
            existing = connection.execute('SELECT role FROM members WHERE project_id=? AND user_id=?',
                                           (project_id, user_id)).fetchone()
            if existing and existing['role'] == 'owner':
                raise ValueError('不能通过成员接口修改项目所有者。')
            connection.execute('INSERT OR REPLACE INTO members VALUES(?,?,?)', (project_id, user_id, role))
            self.store.audit(connection, actor, 'set_member', project_id, {'user_id': user_id, 'role': role})
