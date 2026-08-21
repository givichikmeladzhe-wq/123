#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path

from runtime.control_service import ControlService
from runtime.envelopes import (
    AcceptanceCriterion, AckEnvelope, QAEnvelope, ResultEnvelope, TaskEnvelope,
    now_iso, validate_ack, validate_qa, validate_result, validate_task,
)
from runtime.execution_enforcement import Evidence, EnforcementError
from runtime.execution_store import ExecutionStore
from runtime.run_semantics import RunSemantics


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        store = ExecutionStore(Path(d) / 'bridge.sqlite3')
        control = ControlService(store)
        runs = RunSemantics(store)

        task = TaskEnvelope(
            '1.0','TASK_ENVELOPE','bridge-proof-task','sprint-0b','corr-bridge-001','hermes-1',1,
            'bridge-proof-idem-001',now_iso(),'validate the approved envelope chain without product side effects',(
                AcceptanceCriterion('A1','task/ack/result/qa correlations are valid'),
                AcceptanceCriterion('A2','duplicate dispatch is rejected'),
                AcceptanceCriterion('A3','stale heartbeat fails closed'),
            )
        )
        validate_task(task)
        first = runs.register_idempotency(task.idempotency_key, task.task_id, task.digest)
        duplicate = runs.register_idempotency(task.idempotency_key, task.task_id, task.digest)
        assert first is True and duplicate is False

        control.create_task(task.task_id, task.project_id)
        control.start(task.task_id)
        lease = runs.acquire('run-bridge-001', task.task_id, 'hermes-2', ttl_seconds=90)
        control.executor_running(task.task_id, job_id=lease.run_id, executor_id='hermes-2', live_job=True)

        ack = AckEnvelope('1.0','ACK_ENVELOPE',task.task_id,lease.run_id,task.correlation_id,'hermes-2',2,lease.fencing_token,task.digest,now_iso())
        validate_ack(task, ack)
        runs.heartbeat(lease.run_id, lease.fencing_token, ttl_seconds=90)

        result = ResultEnvelope('1.0','RESULT_ENVELOPE',task.task_id,lease.run_id,task.correlation_id,'hermes-2',3,
                                lease.fencing_token,task.digest,'SUCCEEDED',('artifact://bridge-proof',),
                                {'A1':True,'A2':True,'A3':True},now_iso())
        validate_result(task, ack, result)
        runs.complete(lease.run_id, lease.fencing_token)
        control.material_result(task.task_id,[Evidence('result-envelope',f'sha256:{result.digest}')])
        control.begin_qa(task.task_id,'isolated-qa')

        qa = QAEnvelope('1.0','QA_ENVELOPE',task.task_id,lease.run_id,'qa-bridge-001',task.correlation_id,'isolated-qa',4,
                        lease.fencing_token,task.digest,result.digest,'PASS',{'A1':True,'A2':True,'A3':True},
                        ('evidence://bridge-proof',),now_iso())
        validate_qa(task,ack,result,qa)
        control.qa_result(task.task_id,passed=True,evidence=[Evidence('qa-envelope',f'sha256:{qa.digest}')])

        stale = runs.acquire('run-stale-001','stale-task','hermes-2',ttl_seconds=1)
        future = datetime.now(timezone.utc)+timedelta(seconds=2)
        expired = runs.expire_stale(now=future)
        assert stale.run_id in expired and runs.get(stale.run_id).status == 'STALE'

        snapshot = control.snapshot(task.task_id)
        assert snapshot['state'] == 'PASS'
        evidence = {
            'status':'PASS',
            'task_id':task.task_id,
            'run_id':lease.run_id,
            'qa_run_id':qa.qa_run_id,
            'task_digest':task.digest,
            'ack_digest':ack.digest,
            'result_digest':result.digest,
            'qa_digest':qa.digest,
            'duplicate_rejected': duplicate is False,
            'stale_heartbeat_fail_closed': stale.run_id in expired,
            'final_state':snapshot['state'],
            'event_count':len(control.events(task.task_id)),
        }
        print(json.dumps(evidence,ensure_ascii=False,sort_keys=True))
        store.close()
    return 0


if __name__=='__main__': raise SystemExit(main())
