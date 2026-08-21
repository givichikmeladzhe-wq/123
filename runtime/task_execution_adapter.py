from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from runtime.execution_enforcement import (
    Evidence,
    EnforcementError,
    ExecutionOutcome,
    OutcomeType,
    TaskState,
    claim_done,
    close_execution_turn,
    send_to_qa,
    watchdog,
)


@dataclass
class TaskRecord:
    task_id: str
    project_id: str
    state: TaskState = TaskState.IDLE
    active_executor_id: Optional[str] = None
    active_job_id: Optional[str] = None
    last_material_at: Optional[str] = None
    last_evidence_ref: Optional[str] = None
    owner_action_required: Optional[str] = None


class TaskExecutionAdapter:
    """State-changing boundary for Hermes/Control API execution tasks.

    The adapter deliberately refuses direct DONE/PASS writes. All completion
    must travel through result evidence -> CLAIMED_DONE -> QA -> QA_PASS.
    """

    def __init__(self) -> None:
        self.tasks: Dict[str, TaskRecord] = {}
        self.events: List[dict] = []

    def create_task(self, task_id: str, project_id: str) -> TaskRecord:
        if task_id in self.tasks:
            raise EnforcementError(f"task already exists: {task_id}")
        rec = TaskRecord(task_id=task_id, project_id=project_id)
        self.tasks[task_id] = rec
        self._event(rec, "TASK_CREATED")
        return rec

    def start(self, task_id: str) -> TaskRecord:
        rec = self._get(task_id)
        if rec.state not in {TaskState.IDLE, TaskState.STALLED, TaskState.BLOCKED, TaskState.WAITING_OWNER}:
            raise EnforcementError(f"cannot start from {rec.state}")
        rec.state = TaskState.ACTIVE_EXECUTION
        rec.owner_action_required = None
        self._event(rec, "EXECUTION_STARTED")
        return rec

    def apply_outcome(self, task_id: str, outcome: ExecutionOutcome, *, background_job_alive: bool = False) -> TaskRecord:
        rec = self._get(task_id)
        new_state = close_execution_turn(rec.state, outcome, background_job_alive)
        rec.state = new_state

        if outcome.evidence:
            rec.last_evidence_ref = outcome.evidence[-1].ref
            rec.last_material_at = self._now()

        if outcome.type == OutcomeType.EXECUTOR_RUNNING:
            rec.active_executor_id = outcome.executor_id
            rec.active_job_id = outcome.task_id
        elif new_state != TaskState.ACTIVE_EXECUTION:
            rec.active_job_id = None

        if outcome.type == OutcomeType.OWNER_ACTION_REQUIRED:
            rec.owner_action_required = outcome.owner_action

        self._event(rec, outcome.type.value, outcome)
        return rec

    def claim_result(self, task_id: str, evidence: List[Evidence]) -> TaskRecord:
        rec = self._get(task_id)
        rec.state = claim_done(rec.state, evidence)
        rec.last_evidence_ref = evidence[-1].ref
        rec.last_material_at = self._now()
        rec.active_job_id = None
        self._event(rec, "CLAIMED_DONE")
        return rec

    def begin_qa(self, task_id: str, qa_executor_id: str) -> TaskRecord:
        rec = self._get(task_id)
        if qa_executor_id == rec.active_executor_id and qa_executor_id is not None:
            raise EnforcementError("independent QA required: implementer cannot self-approve")
        rec.state = send_to_qa(rec.state)
        rec.active_executor_id = qa_executor_id
        self._event(rec, "QA_STARTED")
        return rec

    def watchdog_tick(self, task_id: str, *, material_change: bool, live_job: bool) -> TaskRecord:
        rec = self._get(task_id)
        new_state = watchdog(rec.state, material_change, live_job)
        if new_state != rec.state:
            rec.state = new_state
            rec.active_job_id = None
            self._event(rec, "STALLED")
        return rec

    def direct_set_state(self, task_id: str, target: TaskState) -> None:
        if target in {TaskState.CLAIMED_DONE, TaskState.QA, TaskState.PASS, TaskState.BLOCKED, TaskState.WAITING_OWNER}:
            raise EnforcementError(f"direct state write forbidden: {target}")
        raise EnforcementError("all state changes must use execution adapter methods")

    def snapshot(self, task_id: str) -> dict:
        rec = self._get(task_id)
        data = asdict(rec)
        data["state"] = rec.state.value
        return data

    def _get(self, task_id: str) -> TaskRecord:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise EnforcementError(f"unknown task: {task_id}") from exc

    def _event(self, rec: TaskRecord, event_type: str, outcome: Optional[ExecutionOutcome] = None) -> None:
        self.events.append({
            "event_type": event_type,
            "task_id": rec.task_id,
            "project_id": rec.project_id,
            "state": rec.state.value,
            "occurred_at": self._now(),
            "evidence_refs": [e.ref for e in outcome.evidence] if outcome else [],
        })

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
