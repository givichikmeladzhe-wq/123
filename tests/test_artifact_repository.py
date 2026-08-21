import tempfile
import unittest
from pathlib import Path

from runtime.artifact_repository import ArtifactRepository
from runtime.execution_enforcement import EnforcementError


class ArtifactRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = ArtifactRepository(Path(self.tmp.name) / 'control')

    def tearDown(self):
        self.tmp.cleanup()

    def test_immutable_create_and_idempotent_repeat(self):
        first = self.repo.put('tasks','t1',{'task_id':'t1','value':1})
        second = self.repo.put('tasks','t1',{'task_id':'t1','value':1})
        self.assertTrue(first['created']); self.assertFalse(second['created'])
        self.assertEqual(first['sha256'],second['sha256'])
        self.assertEqual(self.repo.get('tasks','t1')['value'],1)

    def test_conflicting_rewrite_is_rejected(self):
        self.repo.put('results','r1',{'status':'ok'})
        with self.assertRaises(EnforcementError):
            self.repo.put('results','r1',{'status':'changed'})

    def test_unsafe_path_is_rejected(self):
        with self.assertRaises(EnforcementError): self.repo.put('tasks','../escape',{'x':1})
        with self.assertRaises(EnforcementError): self.repo.put('secrets','x',{'x':1})

    def test_digest_tamper_is_detected(self):
        self.repo.put('qa','q1',{'verdict':'PASS'})
        path = Path(self.repo.root) / 'qa' / 'q1.json'
        path.write_text('{"verdict":"FAIL"}\n',encoding='utf-8')
        with self.assertRaises(EnforcementError): self.repo.get('qa','q1')


if __name__=='__main__': unittest.main()
