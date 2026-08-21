import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.execution_enforcement import EnforcementError
from runtime.execution_store import ExecutionStore
from runtime.run_semantics import RunSemantics


class RunSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.tmp.name) / 'runs.sqlite3')
        self.runs = RunSemantics(self.store)

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def test_idempotency_duplicate_same_payload_is_safe(self):
        self.assertTrue(self.runs.register_idempotency('k1','t1','hash1'))
        self.assertFalse(self.runs.register_idempotency('k1','t1','hash1'))
        with self.assertRaises(EnforcementError):
            self.runs.register_idempotency('k1','t1','DIFFERENT')

    def test_lease_and_fencing_reject_stale_writer(self):
        r = self.runs.acquire('r1','t1','exec',ttl_seconds=1)
        self.runs.fail('r1', r.fencing_token, 'temporary')
        r2 = self.runs.retry('r1', r.fencing_token)
        self.assertGreater(r2.fencing_token, r.fencing_token)
        with self.assertRaises(EnforcementError):
            self.runs.heartbeat('r1', r.fencing_token)

    def test_active_lease_blocks_second_run(self):
        self.runs.acquire('r1','t1','exec',ttl_seconds=90)
        with self.assertRaises(EnforcementError):
            self.runs.acquire('r2','t1','exec2',ttl_seconds=90)

    def test_expired_lease_becomes_stale(self):
        r = self.runs.acquire('r1','t1','exec',ttl_seconds=1)
        future = datetime.now(timezone.utc) + timedelta(seconds=2)
        self.assertEqual(self.runs.expire_stale(now=future), ['r1'])
        self.assertEqual(self.runs.get('r1').status, 'STALE')

    def test_retry_exhaustion_goes_to_dlq(self):
        r = self.runs.acquire('r1','t1','exec',max_attempts=2)
        r = self.runs.fail('r1',r.fencing_token,'first')
        r = self.runs.retry('r1',r.fencing_token)
        r = self.runs.fail('r1',r.fencing_token,'second',payload={'safe':'metadata'})
        self.assertEqual(r.status,'DLQ')
        self.assertEqual(len(self.runs.dlq()),1)

    def test_cancelled_run_cannot_heartbeat(self):
        r = self.runs.acquire('r1','t1','exec')
        r = self.runs.cancel('r1',r.fencing_token)
        self.assertEqual(r.status,'CANCELLED')
        with self.assertRaises(EnforcementError):
            self.runs.heartbeat('r1',r.fencing_token)


if __name__ == '__main__': unittest.main()
