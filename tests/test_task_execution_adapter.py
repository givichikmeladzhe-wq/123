import unittest

from runtime.execution_enforcement import Evidence, EnforcementError, ExecutionOutcome, OutcomeType, TaskState
from runtime.task_execution_adapter import TaskExecutionAdapter


class TaskExecutionAdapterTests(unittest.TestCase):
    def setUp(self):
        self.a = TaskExecutionAdapter()
        self.a.create_task('t1', 'p1')
        self.a.start('t1')

    def ev(self, ref='evidence://1'):
        return [Evidence('artifact', ref)]

    def test_cannot_self_approve(self):
        self.a.apply_outcome('t1', ExecutionOutcome(OutcomeType.EXECUTOR_RUNNING, task_id='job1', executor_id='impl'), background_job_alive=True)
        self.a.claim_result('t1', self.ev())
        with self.assertRaises(EnforcementError):
            self.a.begin_qa('t1', 'impl')

    def test_full_pass_requires_independent_qa(self):
        self.a.apply_outcome('t1', ExecutionOutcome(OutcomeType.EXECUTOR_RUNNING, task_id='job1', executor_id='impl'), background_job_alive=True)
        self.a.claim_result('t1', self.ev('git://sha'))
        self.a.begin_qa('t1', 'qa')
        rec = self.a.apply_outcome('t1', ExecutionOutcome(OutcomeType.QA_PASS, evidence=self.ev('qa://pass')))
        self.assertEqual(rec.state, TaskState.PASS)

    def test_direct_pass_write_forbidden(self):
        with self.assertRaises(EnforcementError):
            self.a.direct_set_state('t1', TaskState.PASS)

    def test_owner_interrupt_requires_evidence_and_action(self):
        with self.assertRaises(EnforcementError):
            self.a.apply_outcome('t1', ExecutionOutcome(OutcomeType.OWNER_ACTION_REQUIRED))
        rec = self.a.apply_outcome('t1', ExecutionOutcome(OutcomeType.OWNER_ACTION_REQUIRED, evidence=self.ev('error://auth'), owner_action='Reauthorize connector'))
        self.assertEqual(rec.state, TaskState.WAITING_OWNER)

    def test_watchdog_marks_stalled_without_job_or_change(self):
        rec = self.a.watchdog_tick('t1', material_change=False, live_job=False)
        self.assertEqual(rec.state, TaskState.STALLED)

    def test_event_log_is_material(self):
        self.a.apply_outcome('t1', ExecutionOutcome(OutcomeType.ARTIFACT_CHANGED, evidence=self.ev('git://sha2')))
        self.assertGreaterEqual(len(self.a.events), 3)
        self.assertEqual(self.a.events[-1]['evidence_refs'], ['git://sha2'])


if __name__ == '__main__':
    unittest.main()
