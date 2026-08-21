from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Optional

from runtime.execution_enforcement import EnforcementError
from runtime.execution_store import ExecutionStore


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@dataclass
class Lease:
    run_id: str
    task_id: str
    executor_id: str
    fencing_token: int
    lease_expires_at: str
    heartbeat_at: str
    status: str
    attempt: int


class RunSemantics:
    """Persistent lease/idempotency/retry/cancel/DLQ semantics for executor runs."""

    def __init__(self, store: ExecutionStore) -> None:
        self.store = store
        self.db = store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS execution_runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            executor_id TEXT NOT NULL,
            fencing_token INTEGER NOT NULL,
            lease_expires_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            cancelled_at TEXT,
            last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_execution_runs_task ON execution_runs(task_id, status);
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            idempotency_key TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dead_letters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fencing_counters (
            task_id TEXT PRIMARY KEY,
            token INTEGER NOT NULL
        );
        ''')
        self.db.commit()

    def register_idempotency(self, key: str, task_id: str, payload_hash: str) -> bool:
        row = self.db.execute(
            'SELECT task_id, payload_hash FROM idempotency_keys WHERE idempotency_key=?', (key,)
        ).fetchone()
        if row:
            if row['task_id'] != task_id or row['payload_hash'] != payload_hash:
                raise EnforcementError('idempotency key reused with different task/payload')
            return False
        self.db.execute(
            'INSERT INTO idempotency_keys VALUES (?, ?, ?, ?)',
            (key, task_id, payload_hash, iso(utcnow()))
        )
        self.db.commit()
        return True

    def _next_fencing_token(self, task_id: str) -> int:
        row = self.db.execute('SELECT token FROM fencing_counters WHERE task_id=?', (task_id,)).fetchone()
        token = 1 if row is None else int(row['token']) + 1
        self.db.execute(
            'INSERT INTO fencing_counters(task_id, token) VALUES(?, ?) '
            'ON CONFLICT(task_id) DO UPDATE SET token=excluded.token',
            (task_id, token),
        )
        return token

    def acquire(self, run_id: str, task_id: str, executor_id: str, *, ttl_seconds: int = 90, max_attempts: int = 3) -> Lease:
        now = utcnow()
        active = self.db.execute(
            "SELECT * FROM execution_runs WHERE task_id=? AND status='RUNNING' ORDER BY fencing_token DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if active and datetime.fromisoformat(active['lease_expires_at']) > now:
            raise EnforcementError('active lease already exists for task')
        if self.db.execute('SELECT 1 FROM execution_runs WHERE run_id=?', (run_id,)).fetchone():
            raise EnforcementError('run_id already exists')
        token = self._next_fencing_token(task_id)
        expires = now + timedelta(seconds=ttl_seconds)
        self.db.execute('''
            INSERT INTO execution_runs(run_id, task_id, executor_id, fencing_token, lease_expires_at,
                                       heartbeat_at, status, attempt, max_attempts)
            VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', 1, ?)
        ''', (run_id, task_id, executor_id, token, iso(expires), iso(now), max_attempts))
        self.db.commit()
        return self.get(run_id)

    def heartbeat(self, run_id: str, fencing_token: int, *, ttl_seconds: int = 90) -> Lease:
        run = self._row(run_id)
        self._assert_current(run, fencing_token)
        if run['status'] != 'RUNNING':
            raise EnforcementError('heartbeat only valid for RUNNING run')
        now = utcnow(); expires = now + timedelta(seconds=ttl_seconds)
        self.db.execute(
            'UPDATE execution_runs SET heartbeat_at=?, lease_expires_at=? WHERE run_id=?',
            (iso(now), iso(expires), run_id),
        )
        self.db.commit()
        return self.get(run_id)

    def complete(self, run_id: str, fencing_token: int) -> Lease:
        run = self._row(run_id); self._assert_current(run, fencing_token)
        if run['status'] != 'RUNNING': raise EnforcementError('only RUNNING run can complete')
        self.db.execute("UPDATE execution_runs SET status='COMPLETED' WHERE run_id=?", (run_id,))
        self.db.commit(); return self.get(run_id)

    def cancel(self, run_id: str, fencing_token: int) -> Lease:
        run = self._row(run_id); self._assert_current(run, fencing_token)
        if run['status'] not in {'RUNNING','RETRY_WAIT'}: raise EnforcementError('run cannot be cancelled from current status')
        self.db.execute("UPDATE execution_runs SET status='CANCELLED', cancelled_at=? WHERE run_id=?", (iso(utcnow()), run_id))
        self.db.commit(); return self.get(run_id)

    def fail(self, run_id: str, fencing_token: int, error: str, *, payload: Optional[dict] = None) -> Lease:
        run = self._row(run_id); self._assert_current(run, fencing_token)
        if run['status'] != 'RUNNING': raise EnforcementError('only RUNNING run can fail')
        attempt, max_attempts = int(run['attempt']), int(run['max_attempts'])
        if attempt >= max_attempts:
            self.db.execute("UPDATE execution_runs SET status='DLQ', last_error=? WHERE run_id=?", (error, run_id))
            self.db.execute(
                'INSERT INTO dead_letters(run_id, task_id, reason, payload_json, created_at) VALUES (?, ?, ?, ?, ?)',
                (run_id, run['task_id'], error, json.dumps(payload or {}, ensure_ascii=False), iso(utcnow())),
            )
        else:
            self.db.execute(
                "UPDATE execution_runs SET status='RETRY_WAIT', attempt=attempt+1, last_error=? WHERE run_id=?",
                (error, run_id),
            )
        self.db.commit(); return self.get(run_id)

    def retry(self, run_id: str, fencing_token: int, *, ttl_seconds: int = 90) -> Lease:
        run = self._row(run_id); self._assert_current(run, fencing_token)
        if run['status'] != 'RETRY_WAIT': raise EnforcementError('retry only valid from RETRY_WAIT')
        token = self._next_fencing_token(run['task_id'])
        now = utcnow(); expires = now + timedelta(seconds=ttl_seconds)
        self.db.execute(
            "UPDATE execution_runs SET status='RUNNING', fencing_token=?, heartbeat_at=?, lease_expires_at=? WHERE run_id=?",
            (token, iso(now), iso(expires), run_id),
        )
        self.db.commit(); return self.get(run_id)

    def expire_stale(self, *, now: Optional[datetime] = None) -> list[str]:
        now = now or utcnow()
        rows = self.db.execute("SELECT run_id, lease_expires_at FROM execution_runs WHERE status='RUNNING'").fetchall()
        expired = [r['run_id'] for r in rows if datetime.fromisoformat(r['lease_expires_at']) <= now]
        for run_id in expired:
            self.db.execute("UPDATE execution_runs SET status='STALE', last_error='lease expired' WHERE run_id=?", (run_id,))
        self.db.commit(); return expired

    def dlq(self) -> list[dict]:
        return [dict(r) | {'payload': json.loads(r['payload_json'])} for r in self.db.execute('SELECT * FROM dead_letters ORDER BY id').fetchall()]

    def get(self, run_id: str) -> Lease:
        row = self._row(run_id)
        return Lease(run_id=row['run_id'], task_id=row['task_id'], executor_id=row['executor_id'],
                     fencing_token=int(row['fencing_token']), lease_expires_at=row['lease_expires_at'],
                     heartbeat_at=row['heartbeat_at'], status=row['status'], attempt=int(row['attempt']))

    def _row(self, run_id: str):
        row = self.db.execute('SELECT * FROM execution_runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None: raise EnforcementError(f'unknown run: {run_id}')
        return row

    def _assert_current(self, row, fencing_token: int) -> None:
        if int(row['fencing_token']) != int(fencing_token):
            raise EnforcementError('stale fencing token rejected')
