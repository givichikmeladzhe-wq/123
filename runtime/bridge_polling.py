from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from runtime.bridge_roles import DirectorBridge, ExecutorBridge, QABridge
from runtime.envelope_codec import result_from_dict, task_from_dict
from runtime.envelopes import ResultEnvelope, TaskEnvelope
from runtime.execution_enforcement import EnforcementError
from runtime.git_bridge import GitBridgeTransport


PROOF_OBJECTIVE = 'BRIDGE_PROOF_SCHEMA_VALIDATION_V1'
PROOF_PROJECT = 'sprint-0b'


def proof_execute(task: TaskEnvelope) -> tuple[str, tuple[str, ...], dict[str, bool]]:
    if task.project_id != PROOF_PROJECT or task.objective != PROOF_OBJECTIVE:
        raise EnforcementError('proof executor refuses non-proof task')
    results = {c.criterion_id: True for c in task.acceptance_criteria}
    return 'SUCCEEDED', ('artifact://no-side-effect-schema-validation',), results


def proof_review(task: TaskEnvelope, result: ResultEnvelope) -> tuple[str, dict[str, bool], tuple[str, ...]]:
    if task.project_id != PROOF_PROJECT or task.objective != PROOF_OBJECTIVE:
        raise EnforcementError('proof QA refuses non-proof task')
    criteria = {c.criterion_id: bool(result.acceptance_results.get(c.criterion_id)) for c in task.acceptance_criteria}
    verdict = 'PASS' if result.status == 'SUCCEEDED' and all(criteria.values()) else 'FAIL'
    return verdict, criteria, (f'evidence://result-sha256:{result.digest}',)


@dataclass
class H2PollingWorker:
    transport: GitBridgeTransport
    executor: ExecutorBridge

    def process_once(self) -> list[str]:
        processed: list[str] = []
        for task_id in self.transport.list_ids('tasks'):
            run_id = f'run-{task_id}'
            if self.transport.exists('results', run_id):
                continue
            if self.transport.exists('acks', run_id):
                # An ACK without a result represents a prior/in-flight run. Do not create a second lease.
                continue
            task = task_from_dict(self.transport.read('tasks', task_id))
            if task.project_id != PROOF_PROJECT or task.objective != PROOF_OBJECTIVE:
                continue
            self.executor.process(task_id, run_id, proof_execute)
            processed.append(task_id)
        return processed


@dataclass
class QAPollingWorker:
    transport: GitBridgeTransport
    qa: QABridge

    def process_once(self) -> list[str]:
        processed: list[str] = []
        for run_id in self.transport.list_ids('results'):
            result = result_from_dict(self.transport.read('results', run_id))
            qa_run_id = f'qa-{run_id}'
            if self.transport.exists('qa', qa_run_id):
                continue
            task = task_from_dict(self.transport.read('tasks', result.task_id))
            if task.project_id != PROOF_PROJECT or task.objective != PROOF_OBJECTIVE:
                continue
            self.qa.review(task.task_id, run_id, qa_run_id, proof_review)
            processed.append(run_id)
        return processed


@dataclass
class H1PollingCollector:
    transport: GitBridgeTransport
    director: DirectorBridge

    def collect_once(self) -> list[str]:
        completed: list[str] = []
        for task_id in self.transport.list_ids('tasks'):
            run_id = f'run-{task_id}'
            qa_run_id = f'qa-{run_id}'
            if not self.transport.exists('qa', qa_run_id):
                continue
            snapshot = self.director.control.snapshot(task_id)
            if snapshot['state'] == 'PASS':
                continue
            if snapshot['state'] == 'ACTIVE_EXECUTION':
                if self.transport.exists('acks', run_id):
                    self.director.observe_ack(task_id, run_id)
                if self.transport.exists('results', run_id):
                    self.director.observe_result(task_id, run_id)
            if self.director.control.snapshot(task_id)['state'] == 'CLAIMED_DONE':
                self.director.observe_qa(task_id, run_id, qa_run_id)
            if self.director.control.snapshot(task_id)['state'] == 'PASS':
                completed.append(task_id)
        return completed
