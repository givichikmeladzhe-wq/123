from __future__ import annotations

from runtime.envelopes import AcceptanceCriterion, AckEnvelope, QAEnvelope, ResultEnvelope, TaskEnvelope
from runtime.execution_enforcement import EnforcementError


def task_from_dict(p: dict) -> TaskEnvelope:
    try:
        criteria = tuple(AcceptanceCriterion(**x) for x in p['acceptance_criteria'])
        return TaskEnvelope(
            schema_version=p['schema_version'], message_type=p['message_type'], task_id=p['task_id'],
            project_id=p['project_id'], correlation_id=p['correlation_id'], sender_id=p['sender_id'],
            sequence=int(p['sequence']), idempotency_key=p['idempotency_key'], created_at=p['created_at'],
            objective=p['objective'], acceptance_criteria=criteria, context_manifest_ref=p.get('context_manifest_ref')
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EnforcementError(f'invalid TaskEnvelope payload: {exc}') from exc


def ack_from_dict(p: dict) -> AckEnvelope:
    try:
        return AckEnvelope(
            p['schema_version'],p['message_type'],p['task_id'],p['run_id'],p['correlation_id'],p['sender_id'],
            int(p['sequence']),int(p['fencing_token']),p['task_digest'],p['acknowledged_at']
        )
    except (KeyError,TypeError,ValueError) as exc:
        raise EnforcementError(f'invalid AckEnvelope payload: {exc}') from exc


def result_from_dict(p: dict) -> ResultEnvelope:
    try:
        return ResultEnvelope(
            p['schema_version'],p['message_type'],p['task_id'],p['run_id'],p['correlation_id'],p['sender_id'],
            int(p['sequence']),int(p['fencing_token']),p['task_digest'],p['status'],tuple(p['artifact_refs']),
            dict(p['acceptance_results']),p['completed_at']
        )
    except (KeyError,TypeError,ValueError) as exc:
        raise EnforcementError(f'invalid ResultEnvelope payload: {exc}') from exc


def qa_from_dict(p: dict) -> QAEnvelope:
    try:
        return QAEnvelope(
            p['schema_version'],p['message_type'],p['task_id'],p['run_id'],p['qa_run_id'],p['correlation_id'],p['sender_id'],
            int(p['sequence']),int(p['fencing_token']),p['task_digest'],p['result_digest'],p['verdict'],
            dict(p['criterion_results']),tuple(p['evidence_refs']),p['completed_at']
        )
    except (KeyError,TypeError,ValueError) as exc:
        raise EnforcementError(f'invalid QAEnvelope payload: {exc}') from exc
