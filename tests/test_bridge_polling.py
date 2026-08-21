import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.bridge_polling import H1PollingCollector, H2PollingWorker, PROOF_OBJECTIVE, PROOF_PROJECT, QAPollingWorker
from runtime.bridge_roles import DirectorBridge, ExecutorBridge, QABridge
from runtime.control_service import ControlService
from runtime.envelopes import AcceptanceCriterion, TaskEnvelope, now_iso
from runtime.execution_store import ExecutionStore
from runtime.git_bridge import GitBridgeTransport
from runtime.run_semantics import RunSemantics


def git(cwd,*args): subprocess.run(['git',*args],cwd=cwd,check=True,text=True,capture_output=True)


class BridgePollingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        bare=root/'bridge.git'; seed=root/'seed'; h1=root/'h1'; h2=root/'h2'; qa=root/'qa'
        subprocess.run(['git','init','--bare',str(bare)],check=True,capture_output=True,text=True)
        subprocess.run(['git','clone',str(bare),str(seed)],check=True,capture_output=True,text=True)
        git(seed,'config','user.name','seed'); git(seed,'config','user.email','seed@example.invalid')
        (seed/'README.md').write_text('bridge\n'); git(seed,'add','README.md'); git(seed,'commit','-m','seed'); git(seed,'branch','-M','main'); git(seed,'push','-u','origin','main')
        subprocess.run(['git','--git-dir',str(bare),'symbolic-ref','HEAD','refs/heads/main'],check=True,capture_output=True,text=True)
        for path in (h1,h2,qa): subprocess.run(['git','clone',str(bare),str(path)],check=True,capture_output=True,text=True)
        self.th1=GitBridgeTransport(h1); self.th2=GitBridgeTransport(h2); self.tqa=GitBridgeTransport(qa)
        self.th1.configure_identity('hermes-1','h1@example.invalid'); self.th2.configure_identity('hermes-2','h2@example.invalid'); self.tqa.configure_identity('isolated-qa','qa@example.invalid')
        self.s1=ExecutionStore(root/'h1.sqlite3'); self.s2=ExecutionStore(root/'h2.sqlite3')
        self.director=DirectorBridge(self.th1,ControlService(self.s1))
        self.h2=H2PollingWorker(self.th2,ExecutorBridge(self.th2,RunSemantics(self.s2),'hermes-2'))
        self.qa=QAPollingWorker(self.tqa,QABridge(self.tqa,'isolated-qa'))
        self.h1=H1PollingCollector(self.th1,self.director)

    def tearDown(self): self.s1.close(); self.s2.close(); self.tmp.cleanup()

    def task(self, task_id='proof-1', objective=PROOF_OBJECTIVE):
        return TaskEnvelope('1.0','TASK_ENVELOPE',task_id,PROOF_PROJECT,'corr-'+task_id,'hermes-1',1,'idem-'+task_id,now_iso(),objective,(
            AcceptanceCriterion('A1','schema valid'), AcceptanceCriterion('A2','no side effects')
        ))

    def test_polling_chain_reaches_pass_without_owner_intervention(self):
        self.director.dispatch(self.task())
        self.assertEqual(self.h2.process_once(),['proof-1'])
        self.assertEqual(self.qa.process_once(),['run-proof-1'])
        self.assertEqual(self.h1.collect_once(),['proof-1'])
        self.assertEqual(self.director.control.snapshot('proof-1')['state'],'PASS')

    def test_nonproof_task_is_not_executed(self):
        self.director.dispatch(self.task('unsafe-1','DO_PRODUCT_WORK'))
        self.assertEqual(self.h2.process_once(),[])
        self.assertFalse(self.th1.exists('acks','run-unsafe-1'))

    def test_second_poll_is_idempotent(self):
        self.director.dispatch(self.task())
        self.h2.process_once(); self.qa.process_once(); self.h1.collect_once()
        self.assertEqual(self.h2.process_once(),[])
        self.assertEqual(self.qa.process_once(),[])
        self.assertEqual(self.h1.collect_once(),[])


if __name__=='__main__': unittest.main()
