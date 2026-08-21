from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from runtime.control_service import ControlService
from runtime.execution_enforcement import Evidence, EnforcementError
from runtime.execution_store import ExecutionStore


def _evidence(items):
    return [Evidence(kind=i['kind'], ref=i['ref'], digest=i.get('digest')) for i in items or []]


class ControlAPIHandler(BaseHTTPRequestHandler):
    service: ControlService | None = None

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        return json.loads(raw.decode('utf-8'))

    def _segments(self):
        return [p for p in urlparse(self.path).path.split('/') if p]

    def do_GET(self):
        try:
            if self.path == '/healthz':
                return self._json(200, {'status': 'ok'})
            parts = self._segments()
            if len(parts) == 2 and parts[0] == 'tasks':
                task_id = parts[1]
                return self._json(200, {
                    'task': self.service.snapshot(task_id),
                    'events': self.service.events(task_id),
                })
            self._json(404, {'error': 'not_found'})
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self):
        try:
            body = self._body()
            parts = self._segments()
            if parts == ['tasks']:
                rec = self.service.create_task(body['task_id'], body['project_id'])
                return self._json(201, self.service.snapshot(rec.task_id))
            if len(parts) < 3 or parts[0] != 'tasks':
                return self._json(404, {'error': 'not_found'})
            task_id, action = parts[1], '/'.join(parts[2:])
            if action == 'start':
                rec = self.service.start(task_id)
            elif action == 'executor-running':
                rec = self.service.executor_running(
                    task_id, job_id=body['job_id'], executor_id=body['executor_id'], live_job=bool(body['live_job'])
                )
            elif action == 'result':
                rec = self.service.material_result(task_id, _evidence(body['evidence']))
            elif action == 'qa/start':
                rec = self.service.begin_qa(task_id, body['qa_executor_id'])
            elif action == 'qa/result':
                rec = self.service.qa_result(task_id, passed=bool(body['passed']), evidence=_evidence(body['evidence']))
            elif action == 'blocked':
                rec = self.service.blocked(task_id, error=body['error'], evidence=_evidence(body['evidence']))
            elif action == 'owner-action':
                rec = self.service.owner_action(task_id, action=body['action'], evidence=_evidence(body['evidence']))
            elif action == 'watchdog':
                rec = self.service.watchdog(task_id, material_change=bool(body['material_change']), live_job=bool(body['live_job']))
            else:
                return self._json(404, {'error': 'not_found'})
            self._json(200, self.service.snapshot(rec.task_id))
        except Exception as exc:
            self._handle_error(exc)

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, (EnforcementError, KeyError, ValueError, json.JSONDecodeError)):
            self._json(400, {'error': type(exc).__name__, 'detail': str(exc)})
        else:
            self._json(500, {'error': type(exc).__name__, 'detail': str(exc)})

    def log_message(self, fmt, *args):
        return


def serve(host: str = '127.0.0.1', port: int = 8787, db_path: str | Path = 'build/execution.sqlite3') -> None:
    store = ExecutionStore(db_path)
    service = ControlService(store)
    handler = type('BoundControlAPIHandler', (ControlAPIHandler,), {'service': service})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        store.close()


if __name__ == '__main__':
    serve()
