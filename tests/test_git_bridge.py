import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.execution_enforcement import EnforcementError
from runtime.git_bridge import GitBridgeTransport


def git(cwd, *args):
    subprocess.run(['git',*args],cwd=cwd,check=True,text=True,capture_output=True)


class GitBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        self.bare=root/'bridge.git'; self.seed=root/'seed'; self.h1=root/'h1'; self.h2=root/'h2'
        subprocess.run(['git','init','--bare',str(self.bare)],check=True,capture_output=True,text=True)
        subprocess.run(['git','clone',str(self.bare),str(self.seed)],check=True,capture_output=True,text=True)
        git(self.seed,'config','user.name','seed'); git(self.seed,'config','user.email','seed@example.invalid')
        (self.seed/'README.md').write_text('bridge\n'); git(self.seed,'add','README.md'); git(self.seed,'commit','-m','seed'); git(self.seed,'branch','-M','main'); git(self.seed,'push','-u','origin','main')
        subprocess.run(['git','--git-dir',str(self.bare),'symbolic-ref','HEAD','refs/heads/main'],check=True,capture_output=True,text=True)
        subprocess.run(['git','clone',str(self.bare),str(self.h1)],check=True,capture_output=True,text=True)
        subprocess.run(['git','clone',str(self.bare),str(self.h2)],check=True,capture_output=True,text=True)
        self.t1=GitBridgeTransport(self.h1); self.t2=GitBridgeTransport(self.h2)
        self.t1.configure_identity('hermes-1','h1@example.invalid'); self.t2.configure_identity('hermes-2','h2@example.invalid')

    def tearDown(self): self.tmp.cleanup()

    def test_round_trip_task_ack_result_qa(self):
        self.t1.publish('tasks','t1',{'type':'TASK_ENVELOPE','task_id':'t1'},message='task t1')
        self.assertEqual(self.t2.read('tasks','t1')['task_id'],'t1')
        self.t2.publish('acks','t1-r1',{'type':'ACK_ENVELOPE','task_id':'t1','run_id':'r1'},message='ack t1')
        self.assertEqual(self.t1.read('acks','t1-r1')['run_id'],'r1')
        self.t2.publish('results','r1',{'type':'RESULT_ENVELOPE','run_id':'r1','status':'SUCCEEDED'},message='result r1')
        self.assertEqual(self.t1.read('results','r1')['status'],'SUCCEEDED')
        self.t1.publish('qa','q1',{'type':'QA_ENVELOPE','run_id':'r1','verdict':'PASS'},message='qa q1')
        self.assertEqual(self.t2.read('qa','q1')['verdict'],'PASS')

    def test_duplicate_same_artifact_has_no_second_commit(self):
        first=self.t1.publish('tasks','t1',{'task_id':'t1'},message='task')
        second=self.t1.publish('tasks','t1',{'task_id':'t1'},message='duplicate')
        self.assertTrue(first['created']); self.assertFalse(second['created']); self.assertEqual(first['commit'],second['commit'])

    def test_conflicting_duplicate_rejected(self):
        self.t1.publish('tasks','t1',{'task_id':'t1','v':1},message='task')
        with self.assertRaises(EnforcementError): self.t1.publish('tasks','t1',{'task_id':'t1','v':2},message='conflict')


if __name__=='__main__': unittest.main()
