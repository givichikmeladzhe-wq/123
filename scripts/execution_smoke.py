#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.control_service import ControlService
from runtime.execution_enforcement import Evidence
from runtime.execution_store import ExecutionStore


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        store = ExecutionStore(Path(d) / 'execution.sqlite3')
        svc = ControlService(store)
        svc.create_task('smoke-task', 'smoke-project')
        svc.start('smoke-task')
        svc.executor_running('smoke-task', job_id='job-smoke-1', executor_id='implementer', live_job=True)
        svc.material_result('smoke-task', [Evidence('artifact', 'smoke://artifact')])
        svc.begin_qa('smoke-task', 'qa')
        svc.qa_result('smoke-task', passed=True, evidence=[Evidence('qa_report', 'smoke://qa-pass')])
        snapshot = svc.snapshot('smoke-task')
        events = svc.events('smoke-task')
        assert snapshot['state'] == 'PASS', snapshot
        assert events[-1]['event_type'] == 'QA_PASS', events
        print(json.dumps({'status': 'PASS', 'snapshot': snapshot, 'events': len(events)}, ensure_ascii=False))
        store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
