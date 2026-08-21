from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from runtime.control_service import ControlService
from runtime.envelope_codec import ack_from_dict, qa_from_dict, result_from_dict, task_from_dict
from runtime.envelopes import AckEnvelope, QAEnvelope, ResultEnvelope, TaskEnvelope, now_iso, validate_ack, validate_qa, validate_result, validate_task
from runtime.execution_enforcement import Evidence, EnforcementError
from runtime.git_bridge import GitBridgeTransport
from runtime.run_semantics import RunSemantics


ExecuteFn = Callable[[TaskEnvelope], tuple[str, tuple[str, ...], dict[str, bool]]]
QaFn = Callable[[TaskEnvelope, ResultEnvelope], tuple[str, dict[str, bool], tuple[str, ...]]]


@dataclass
class DirectorBridge:
    transport: GitBridgeTransport
    control: ControlService

    def dispatch(self, task: TaskEnvelope) -> str:
        validate_task(task)
        try:
            self.control.create_task(task.task_id, task.project_id)
            self.control.start(task.task_id)
        except EnforcementError as exc:
            snapshot = self.control.snapshot(task.task_id)
            if snapshot['state'] not in {'ACTIVE_EXECUTION','STALLED','BLOCKED'}:
                raise
        result = self.transport.publish('tasks', task.task_id, task.payload(), message=f'task {task.task_id}')
        return str(result['commit'])

    def observe_ack(self, task_id: str, run_id: str) -> AckEnvelope:
        task = task_from_dict(self.transport.read('tasks', task_id))
        ack = ack_from_dict(self.transport.read('acks', run_id))
        validate_ack(task, ack)
        self.control.executor_running(task_id, job_id=run_id, executor_id=ack.sender_id, live_job=True)
        return ack

    def observe_result(self, task_id: str, run_id: str) -> ResultEnvelope:
        task = task_from_dict(self.transport.read('tasks', task_id))
        ack = ack_from_dict(self.transport.read('acks', run_id))
        result = result_from_dict(self.transport.read('results', run_id))
        validate_result(task, ack, result)
        self.control.material_result(task_id, [Evidence('result-envelope', f'sha256:{result.digest}')])
        return result

    def observe_qa(self, task_id: str, run_id: str, qa_run_id: str) -> QAEnvelope:
        task = task_from_dict(self.transport.read('tasks', task_id))
        ack = ack_from_dict(self.transport.read('acks', run_id))
        result = result_from_dict(self.transport.read('results', run_id))
        qa = qa_from_dict(self.transport.read('qa', qa_run_id))
        validate_qa(task, ack, result, qa)
        self.control.begin_qa(task_id, qa.sender_id)
        self.control.qa_result(task_id, passed=qa.verdict == 'PASS', evidence=[Evidence('qa-envelope', f'sha256:{qa.digest}')])
        return qa


@dataclass
class ExecutorBridge:
    transport: GitBridgeTransport
    runs: RunSemantics
    executor_id: str = 'hermes-2'

    def process(self, task_id: str, run_id: str, execute: ExecuteFn) -> ResultEnvelope:
        task = task_from_dict(self.transport.read('tasks', task_id))
        validate_task(task)
        if not self.runs.register_idempotency(task.idempotency_key, task.task_id, task.digest):
            raise EnforcementError('duplicate task dispatch rejected')
        lease = self.runs.acquire(run_id, task.task_id, self.executor_id, ttl_seconds=90)
        ack = AckEnvelope('1.0','ACK_ENVELOPE',task.task_id,run_id,task.correlation_id,self.executor_id,
                          task.sequence + 1,lease.fencing_token,task.digest,now_iso())
        validate_ack(task, ack)
        self.transport.publish('acks',run_id,ack.payload(),message=f'ack {run_id}')
        self.runs.heartbeat(run_id,lease.fencing_token,ttl_seconds=90)
        status, artifact_refs, acceptance_results = execute(task)
        result = ResultEnvelope('1.0','RESULT_ENVELOPE',task.task_id,run_id,task.correlation_id,self.executor_id,
                                ack.sequence + 1,lease.fencing_token,task.digest,status,artifact_refs,acceptance_results,now_iso())
        validate_result(task,ack,result)
        if status == 'SUCCEEDED':
            self.runs.complete(run_id,lease.fencing_token)
        else:
            self.runs.fail(run_id,lease.fencing_token,f'executor status={status}',payload={'task_id':task.task_id})
        self.transport.publish('results',run_id,result.payload(),message=f'result {run_id}')
        return result


@dataclass
class QABridge:
    transport: GitBridgeTransport
    qa_id: str = 'isolated-qa'

    def review(self, task_id: str, run_id: str, qa_run_id: str, evaluate: QaFn) -> QAEnvelope:
        task = task_from_dict(self.transport.read('tasks',task_id))
        ack = ack_from_dict(self.transport.read('acks',run_id))
        result = result_from_dict(self.transport.read('results',run_id))
        validate_result(task,ack,result)
        if self.qa_id in {task.sender_id,result.sender_id}:
            raise EnforcementError('QA identity must be independent')
        verdict, criterion_results, evidence_refs = evaluate(task,result)
        qa = QAEnvelope('1.0','QA_ENVELOPE',task.task_id,run_id,qa_run_id,task.correlation_id,self.qa_id,
                        result.sequence + 1,result.fencing_token,task.digest,result.digest,verdict,
                        criterion_results,evidence_refs,now_iso())
        validate_qa(task,ack,result,qa)
        self.transport.publish('qa',qa_run_id,qa.payload(),message=f'qa {qa_run_id}')
        return qa
