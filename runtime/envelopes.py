from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from runtime.execution_enforcement import EnforcementError


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    description: str


@dataclass(frozen=True)
class TaskEnvelope:
    schema_version: str
    message_type: Literal['TASK_ENVELOPE']
    task_id: str
    project_id: str
    correlation_id: str
    sender_id: str
    sequence: int
    idempotency_key: str
    created_at: str
    objective: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    context_manifest_ref: str | None = None

    def payload(self) -> dict:
        return asdict(self)

    @property
    def digest(self) -> str:
        return sha256_json(self.payload())


@dataclass(frozen=True)
class AckEnvelope:
    schema_version: str
    message_type: Literal['ACK_ENVELOPE']
    task_id: str
    run_id: str
    correlation_id: str
    sender_id: str
    sequence: int
    fencing_token: int
    task_digest: str
    acknowledged_at: str

    def payload(self) -> dict: return asdict(self)
    @property
    def digest(self) -> str: return sha256_json(self.payload())


@dataclass(frozen=True)
class HeartbeatEnvelope:
    schema_version: str
    message_type: Literal['HEARTBEAT_ENVELOPE']
    task_id: str
    run_id: str
    correlation_id: str
    sender_id: str
    sequence: int
    fencing_token: int
    sent_at: str

    def payload(self) -> dict: return asdict(self)
    @property
    def digest(self) -> str: return sha256_json(self.payload())


@dataclass(frozen=True)
class ResultEnvelope:
    schema_version: str
    message_type: Literal['RESULT_ENVELOPE']
    task_id: str
    run_id: str
    correlation_id: str
    sender_id: str
    sequence: int
    fencing_token: int
    task_digest: str
    status: Literal['SUCCEEDED', 'FAILED', 'BLOCKED']
    artifact_refs: tuple[str, ...]
    acceptance_results: dict[str, bool]
    completed_at: str

    def payload(self) -> dict: return asdict(self)
    @property
    def digest(self) -> str: return sha256_json(self.payload())


@dataclass(frozen=True)
class QAEnvelope:
    schema_version: str
    message_type: Literal['QA_ENVELOPE']
    task_id: str
    run_id: str
    qa_run_id: str
    correlation_id: str
    sender_id: str
    sequence: int
    fencing_token: int
    task_digest: str
    result_digest: str
    verdict: Literal['PASS', 'FAIL']
    criterion_results: dict[str, bool]
    evidence_refs: tuple[str, ...]
    completed_at: str

    def payload(self) -> dict: return asdict(self)
    @property
    def digest(self) -> str: return sha256_json(self.payload())


def validate_task(task: TaskEnvelope) -> None:
    if task.schema_version != '1.0': raise EnforcementError('unsupported TaskEnvelope schema')
    if task.message_type != 'TASK_ENVELOPE': raise EnforcementError('invalid task message_type')
    required = [task.task_id, task.project_id, task.correlation_id, task.sender_id, task.idempotency_key, task.objective]
    if not all(required): raise EnforcementError('TaskEnvelope contains empty required field')
    if task.sequence < 1: raise EnforcementError('task sequence must be positive')
    if not task.acceptance_criteria: raise EnforcementError('acceptance criteria required')
    ids = [c.criterion_id for c in task.acceptance_criteria]
    if len(ids) != len(set(ids)): raise EnforcementError('duplicate acceptance criterion id')


def validate_ack(task: TaskEnvelope, ack: AckEnvelope) -> None:
    if (ack.task_id, ack.correlation_id, ack.task_digest) != (task.task_id, task.correlation_id, task.digest):
        raise EnforcementError('ACK correlation/hash mismatch')
    if ack.fencing_token < 1 or ack.sequence <= task.sequence:
        raise EnforcementError('ACK fencing/sequence invalid')


def validate_result(task: TaskEnvelope, ack: AckEnvelope, result: ResultEnvelope) -> None:
    validate_ack(task, ack)
    if (result.task_id, result.run_id, result.correlation_id) != (task.task_id, ack.run_id, task.correlation_id):
        raise EnforcementError('Result correlation mismatch')
    if result.fencing_token != ack.fencing_token: raise EnforcementError('stale result fencing token')
    if result.task_digest != task.digest: raise EnforcementError('Result task hash mismatch')
    if result.sequence <= ack.sequence: raise EnforcementError('Result sequence invalid')
    required_ids = {c.criterion_id for c in task.acceptance_criteria}
    if set(result.acceptance_results) != required_ids: raise EnforcementError('Result acceptance results incomplete')
    if result.status == 'SUCCEEDED' and not all(result.acceptance_results.values()):
        raise EnforcementError('SUCCEEDED result has failed acceptance criterion')


def validate_qa(task: TaskEnvelope, ack: AckEnvelope, result: ResultEnvelope, qa: QAEnvelope) -> None:
    validate_result(task, ack, result)
    if (qa.task_id, qa.run_id, qa.correlation_id) != (task.task_id, result.run_id, task.correlation_id):
        raise EnforcementError('QA correlation mismatch')
    if qa.sender_id in {task.sender_id, result.sender_id}: raise EnforcementError('QA identity is not independent')
    if qa.fencing_token != result.fencing_token: raise EnforcementError('QA fencing mismatch')
    if qa.task_digest != task.digest or qa.result_digest != result.digest: raise EnforcementError('QA evidence hash mismatch')
    if qa.sequence <= result.sequence: raise EnforcementError('QA sequence invalid')
    required_ids = {c.criterion_id for c in task.acceptance_criteria}
    if set(qa.criterion_results) != required_ids: raise EnforcementError('QA criterion results incomplete')
    if qa.verdict == 'PASS' and not all(qa.criterion_results.values()):
        raise EnforcementError('QA PASS contains failed criterion')
    if not qa.evidence_refs: raise EnforcementError('QA evidence required')
