from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from runtime.execution_enforcement import TaskState
from runtime.task_execution_adapter import TaskRecord


class ExecutionStore:
    """Thread-safe SQLite persistence for task snapshots and append-only execution events."""

    def __init__(self, path: str | Path = ':memory:') -> None:
        self.path = str(path)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self._init_schema()

    def _init_schema(self) -> None:
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS execution_tasks (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            state TEXT NOT NULL,
            active_executor_id TEXT,
            active_job_id TEXT,
            last_material_at TEXT,
            last_evidence_ref TEXT,
            owner_action_required TEXT
        );
        CREATE TABLE IF NOT EXISTS execution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            state TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_execution_events_task_id ON execution_events(task_id, id);
        ''')
        self.db.commit()

    def save_task(self, record: TaskRecord) -> None:
        with self.lock:
            self.db.execute('''
            INSERT INTO execution_tasks (
                task_id, project_id, state, active_executor_id, active_job_id,
                last_material_at, last_evidence_ref, owner_action_required
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                project_id=excluded.project_id,
                state=excluded.state,
                active_executor_id=excluded.active_executor_id,
                active_job_id=excluded.active_job_id,
                last_material_at=excluded.last_material_at,
                last_evidence_ref=excluded.last_evidence_ref,
                owner_action_required=excluded.owner_action_required
            ''', (
                record.task_id, record.project_id, record.state.value,
                record.active_executor_id, record.active_job_id,
                record.last_material_at, record.last_evidence_ref,
                record.owner_action_required,
            ))
            self.db.commit()

    def load_task(self, task_id: str) -> Optional[TaskRecord]:
        with self.lock:
            row = self.db.execute('SELECT * FROM execution_tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=row['task_id'], project_id=row['project_id'], state=TaskState(row['state']),
            active_executor_id=row['active_executor_id'], active_job_id=row['active_job_id'],
            last_material_at=row['last_material_at'], last_evidence_ref=row['last_evidence_ref'],
            owner_action_required=row['owner_action_required'],
        )

    def append_event(self, event: dict) -> None:
        with self.lock:
            self.db.execute('''
            INSERT INTO execution_events (
                task_id, project_id, event_type, state, occurred_at, evidence_refs_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                event['task_id'], event['project_id'], event['event_type'], event['state'], event['occurred_at'],
                json.dumps(event.get('evidence_refs', []), ensure_ascii=False),
            ))
            self.db.commit()

    def list_events(self, task_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute('SELECT * FROM execution_events WHERE task_id=? ORDER BY id', (task_id,)).fetchall()
        return [{
            'id': row['id'], 'task_id': row['task_id'], 'project_id': row['project_id'],
            'event_type': row['event_type'], 'state': row['state'], 'occurred_at': row['occurred_at'],
            'evidence_refs': json.loads(row['evidence_refs_json']),
        } for row in rows]

    def close(self) -> None:
        with self.lock:
            self.db.close()
