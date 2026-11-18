"""SQLite storage with transactional audit events."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
 admin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
 digest TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members (
 project_id TEXT REFERENCES projects(id), user_id TEXT REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('owner','member','expert','rule_admin')),
 PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS cases (
 id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), thread_id TEXT UNIQUE,
 status TEXT NOT NULL, state TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS feedback (
 id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id), expert_id TEXT REFERENCES users(id),
 payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rule_versions (
 project_id TEXT REFERENCES projects(id), rule_id TEXT NOT NULL, version TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(project_id,rule_id,version));
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
 target TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
PRAGMA user_version=1;
"""


def utcnow() -> str:
    """Return an unambiguous audit timestamp."""
    return datetime.now(timezone.utc).isoformat()


class SQLiteStore:
    """Open one short-lived connection per operation for concurrent clients."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit data and audit together, rolling back on failure."""
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def audit(connection: sqlite3.Connection, actor: str, action: str,
              target: str, detail: object = None) -> None:
        """Append an event without storing passwords or authentication tokens."""
        connection.execute(
            "INSERT INTO audit(actor,action,target,detail,created_at) VALUES(?,?,?,?,?)",
            (actor, action, target, json.dumps(detail, ensure_ascii=False), utcnow()),
        )
