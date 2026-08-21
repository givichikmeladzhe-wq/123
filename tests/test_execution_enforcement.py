import unittest
from runtime.execution_enforcement import *

class ExecutionEnforcementTests(unittest.TestCase):
    def ev(self): return [Evidence('log','evidence://test')]
    def test_prose_only_rejected(self):
        with self.assertRaises(EnforcementError): close_execution_turn(TaskState.ACTIVE_EXECUTION, ExecutionOutcome(OutcomeType.NO_PROGRESS))
    def test_fake_background_rejected(self):
        with self.assertRaises(EnforcementError): close_execution_turn(TaskState.ACTIVE_EXECUTION, ExecutionOutcome(OutcomeType.EXECUTOR_RUNNING,task_id='1',executor_id='codex'),False)
    def test_blocker_requires_evidence(self):
        with self.assertRaises(EnforcementError): close_execution_turn(TaskState.ACTIVE_EXECUTION, ExecutionOutcome(OutcomeType.BLOCKED_WITH_EVIDENCE,error='ssh failed'))
    def test_done_requires_qa(self):
        s=claim_done(TaskState.ACTIVE_EXECUTION,self.ev()); self.assertEqual(s,TaskState.CLAIMED_DONE)
        s=send_to_qa(s); self.assertEqual(s,TaskState.QA)
        s=close_execution_turn(s,ExecutionOutcome(OutcomeType.QA_PASS,evidence=self.ev())); self.assertEqual(s,TaskState.PASS)
    def test_watchdog_stalls_empty_execution(self):
        self.assertEqual(watchdog(TaskState.ACTIVE_EXECUTION,False,False),TaskState.STALLED)

if __name__=='__main__': unittest.main()
