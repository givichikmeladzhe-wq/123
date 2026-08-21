import tempfile
import unittest
from pathlib import Path

from runtime.control_service import ControlService
from runtime.execution_enforcement import Evidence, EnforcementError, TaskState
from runtime.execution_store import ExecutionStore


class ControlServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'execution.sqlite3'
        self.store = ExecutionStore(self.db_path)
        self.svc = ControlService(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def ev(self, ref):
        return [Evidence('artifact', ref)]

    def test_persistent_e2e_pass(self):
        self.svc.create_task('t1', 'p1')
        self.svc.start('t1')
        self.svc.executor_running('t1', job_id='job-1', executor_id='impl', live_job=True)
        self.svc.material_result('t1', self.ev('git://sha1'))
        self.svc.begin_qa('t1', 'qa')
        rec = self.svc.qa_result('t1', passed=True, evidence=self.ev('qa://pass1'))
        self.assertEqual(rec.state, TaskState.PASS)
        self.assertEqual(self.store.load_task('t1').state, TaskState.PASS)
        self.assertEqual([e['event_type'] for e in self.svc.events('t1')], [
            'TASK_CREATED', 'EXECUTION_STARTED', 'EXECUTOR_RUNNING', 'CLAIMED_DONE', 'QA_STARTED', 'QA_PASS'
        ])

    def test_restart_hydrates_state(self):
        self.svc.create_task('t2', 'p1')
        self.svc.start('t2')
        self.store.close()
        self.store = ExecutionStore(self.db_path)
        self.svc = ControlService(self.store)
        self.assertEqual(self.svc.snapshot('t2')['state'], 'ACTIVE_EXECUTION')

    def test_fake_running_is_rejected(self):
        self.svc.create_task('t3', 'p1')
        self.svc.start('t3')
        with self.assertRaises(EnforcementError):
            self.svc.executor_running('t3', job_id='job-3', executor_id='impl', live_job=False)

    def test_qa_fail_reopens_execution(self):
        self.svc.create_task('t4', 'p1')
        self.svc.start('t4')
        self.svc.executor_running('t4', job_id='job-4', executor_id='impl', live_job=True)
        self.svc.material_result('t4', self.ev('git://sha4'))
        self.svc.begin_qa('t4', 'qa')
        rec = self.svc.qa_result('t4', passed=False, evidence=self.ev('qa://fail4'))
        self.assertEqual(rec.state, TaskState.ACTIVE_EXECUTION)


if __name__ == '__main__':
    unittest.main()
