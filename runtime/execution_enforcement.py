from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set

class TaskState(str, Enum):
    IDLE='IDLE'; ACTIVE_EXECUTION='ACTIVE_EXECUTION'; CLAIMED_DONE='CLAIMED_DONE'; QA='QA'; PASS='PASS'; BLOCKED='BLOCKED'; WAITING_OWNER='WAITING_OWNER'; STALLED='STALLED'; CANCELLED_BY_OWNER='CANCELLED_BY_OWNER'

class OutcomeType(str, Enum):
    ARTIFACT_CREATED='ARTIFACT_CREATED'; ARTIFACT_CHANGED='ARTIFACT_CHANGED'; EXECUTOR_RUNNING='EXECUTOR_RUNNING'; TEST_EXECUTED='TEST_EXECUTED'; DEPLOY_EXECUTED='DEPLOY_EXECUTED'; BLOCKED_WITH_EVIDENCE='BLOCKED_WITH_EVIDENCE'; QA_PASS='QA_PASS'; QA_FAIL='QA_FAIL'; OWNER_ACTION_REQUIRED='OWNER_ACTION_REQUIRED'; CANCELLED_BY_OWNER='CANCELLED_BY_OWNER'; NO_PROGRESS='NO_PROGRESS'

@dataclass
class Evidence:
    kind: str
    ref: str
    digest: Optional[str] = None

@dataclass
class ExecutionOutcome:
    type: OutcomeType
    evidence: List[Evidence] = field(default_factory=list)
    task_id: Optional[str] = None
    executor_id: Optional[str] = None
    owner_action: Optional[str] = None
    error: Optional[str] = None

class EnforcementError(RuntimeError): pass

MATERIAL: Set[OutcomeType] = {OutcomeType.ARTIFACT_CREATED,OutcomeType.ARTIFACT_CHANGED,OutcomeType.EXECUTOR_RUNNING,OutcomeType.TEST_EXECUTED,OutcomeType.DEPLOY_EXECUTED,OutcomeType.BLOCKED_WITH_EVIDENCE,OutcomeType.QA_PASS,OutcomeType.QA_FAIL,OutcomeType.OWNER_ACTION_REQUIRED,OutcomeType.CANCELLED_BY_OWNER}

def validate_outcome(o: ExecutionOutcome) -> None:
    if o.type == OutcomeType.NO_PROGRESS or o.type not in MATERIAL: raise EnforcementError('execution turn has no material outcome')
    if o.type in {OutcomeType.ARTIFACT_CREATED,OutcomeType.ARTIFACT_CHANGED,OutcomeType.TEST_EXECUTED,OutcomeType.DEPLOY_EXECUTED,OutcomeType.BLOCKED_WITH_EVIDENCE,OutcomeType.QA_PASS,OutcomeType.QA_FAIL,OutcomeType.OWNER_ACTION_REQUIRED} and not o.evidence: raise EnforcementError(f'{o.type} requires evidence')
    if o.type == OutcomeType.EXECUTOR_RUNNING and (not o.task_id or not o.executor_id): raise EnforcementError('EXECUTOR_RUNNING requires task_id and executor_id')
    if o.type == OutcomeType.BLOCKED_WITH_EVIDENCE and not o.error: raise EnforcementError('BLOCKED requires concrete error')
    if o.type == OutcomeType.OWNER_ACTION_REQUIRED and not o.owner_action: raise EnforcementError('owner interruption requires one minimal action')

def close_execution_turn(state: TaskState, o: ExecutionOutcome, background_job_alive: bool=False) -> TaskState:
    validate_outcome(o)
    if o.type == OutcomeType.EXECUTOR_RUNNING:
        if not background_job_alive: raise EnforcementError('fake background work rejected: no live job')
        return TaskState.ACTIVE_EXECUTION
    if o.type == OutcomeType.BLOCKED_WITH_EVIDENCE: return TaskState.BLOCKED
    if o.type == OutcomeType.OWNER_ACTION_REQUIRED: return TaskState.WAITING_OWNER
    if o.type == OutcomeType.CANCELLED_BY_OWNER: return TaskState.CANCELLED_BY_OWNER
    if o.type == OutcomeType.QA_PASS:
        if state != TaskState.QA: raise EnforcementError('QA_PASS only from QA')
        return TaskState.PASS
    if o.type == OutcomeType.QA_FAIL:
        if state != TaskState.QA: raise EnforcementError('QA_FAIL only from QA')
        return TaskState.ACTIVE_EXECUTION
    return TaskState.ACTIVE_EXECUTION

def claim_done(state: TaskState, evidence: List[Evidence]) -> TaskState:
    if state != TaskState.ACTIVE_EXECUTION or not evidence: raise EnforcementError('CLAIMED_DONE requires ACTIVE_EXECUTION and evidence')
    return TaskState.CLAIMED_DONE

def send_to_qa(state: TaskState) -> TaskState:
    if state != TaskState.CLAIMED_DONE: raise EnforcementError('QA requires CLAIMED_DONE')
    return TaskState.QA

def watchdog(state: TaskState, material_change: bool, live_job: bool) -> TaskState:
    return TaskState.STALLED if state == TaskState.ACTIVE_EXECUTION and not material_change and not live_job else state
