from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from runtime.execution_enforcement import Evidence, ExecutionOutcome, OutcomeType, TaskState
from runtime.execution_store import ExecutionStore
from runtime.task_execution_adapter import TaskExecutionAdapter, TaskRecord


class ControlService:
    """Persistent execution boundary for Hermes/Control API.

    Adapter owns validation/state transitions. Store owns durable snapshots/events.
    """

    def __init__(self, store: ExecutionStore) -> None:
        self.store = store
        self.adapter = TaskExecutionAdapter()

    def _hydrate(self, task_id: str) -> None:
        if task_id in self.adapter.tasks:
            return
        rec = self.store.load_task(task_id)
        if rec is not None:
            self.adapter.tasks[task_id] = rec

    def _persist_new_events(self, before: int, rec: TaskRecord) -> TaskRecord:
        self.store.save_task(rec)
        for event in self.adapter.events[before:]:
            self.store.append_event(event)
        return rec

    def create_task(self, task_id: str, project_id: str) -> TaskRecord:
        before = len(self.adapter.events)
        rec = self.adapter.create_task(task_id, project_id)
        return self._persist_new_events(before, rec)

    def start(self, task_id: str) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.start(task_id)
        return self._persist_new_events(before, rec)

    def executor_running(self, task_id: str, *, job_id: str, executor_id: str, live_job: bool) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.apply_outcome(
            task_id,
            ExecutionOutcome(OutcomeType.EXECUTOR_RUNNING, task_id=job_id, executor_id=executor_id),
            background_job_alive=live_job,
        )
        return self._persist_new_events(before, rec)

    def material_result(self, task_id: str, evidence: Iterable[Evidence]) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.claim_result(task_id, list(evidence))
        return self._persist_new_events(before, rec)

    def begin_qa(self, task_id: str, qa_executor_id: str) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.begin_qa(task_id, qa_executor_id)
        return self._persist_new_events(before, rec)

    def qa_result(self, task_id: str, *, passed: bool, evidence: Iterable[Evidence]) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        kind = OutcomeType.QA_PASS if passed else OutcomeType.QA_FAIL
        rec = self.adapter.apply_outcome(task_id, ExecutionOutcome(kind, evidence=list(evidence)))
        return self._persist_new_events(before, rec)

    def blocked(self, task_id: str, *, error: str, evidence: Iterable[Evidence]) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.apply_outcome(
            task_id,
            ExecutionOutcome(OutcomeType.BLOCKED_WITH_EVIDENCE, evidence=list(evidence), error=error),
        )
        return self._persist_new_events(before, rec)

    def owner_action(self, task_id: str, *, action: str, evidence: Iterable[Evidence]) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.apply_outcome(
            task_id,
            ExecutionOutcome(OutcomeType.OWNER_ACTION_REQUIRED, evidence=list(evidence), owner_action=action),
        )
        return self._persist_new_events(before, rec)

    def watchdog(self, task_id: str, *, material_change: bool, live_job: bool) -> TaskRecord:
        self._hydrate(task_id)
        before = len(self.adapter.events)
        rec = self.adapter.watchdog_tick(task_id, material_change=material_change, live_job=live_job)
        return self._persist_new_events(before, rec)

    def snapshot(self, task_id: str) -> dict:
        self._hydrate(task_id)
        return self.adapter.snapshot(task_id)

    def events(self, task_id: str) -> list[dict]:
        return self.store.list_events(task_id)
