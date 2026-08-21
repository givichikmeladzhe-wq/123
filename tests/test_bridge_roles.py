import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.bridge_roles import DirectorBridge, ExecutorBridge, QABridge
from runtime.control_service import ControlService
from runtime.envelopes import AcceptanceCriterion, TaskEnvelope, now_iso
from runtime.execution_store import ExecutionStore
from runtime.git_bridge import GitBridgeTransport
from runtime.run_semantics import RunSemantics


def git(cwd,*args): subprocess.run(['git',*args],cwd=cwd,check=True,text=True,capture_output=True)


class BridgeRolesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        bare=root/'bridge.git'; seed=root/'seed'; h1=root/'h1'; h2=root/'h2'; qa=root/'qa'
        subprocess.run(['git','init','--bare',str(bare)],check=True,capture_output=True,text=True)
        subprocess.run(['git','clone',str(bare),str(seed)],check=True,capture_output=True,text=True)
        git(seed,'config','user.name','seed'); git(seed,'config','user.email','seed@example.invalid')
        (seed/'README.md').write_text('bridge\n'); git(seed,'add','README.md'); git(seed,'commit','-m','seed'); git(seed,'branch','-M','main'); git(seed,'push','-u','origin','main')
        subprocess.run(['git','--git-dir',str(bare),'symbolic-ref','HEAD','refs/heads/main'],check=True,capture_output=True,text=True)
        for path in (h1,h2,qa): subprocess.run(['git','clone',str(bare),str(path)],check=True,capture_output=True,text=True)
        self.t_h1=GitBridgeTransport(h1); self.t_h2=GitBridgeTransport(h2); self.t_qa=GitBridgeTransport(qa)
        self.t_h1.configure_identity('hermes-1','h1@example.invalid'); self.t_h2.configure_identity('hermes-2','h2@example.invalid'); self.t_qa.configure_identity('isolated-qa','qa@example.invalid')
        self.h1_store=ExecutionStore(root/'h1.sqlite3'); self.h2_store=ExecutionStore(root/'h2.sqlite3')
        self.director=DirectorBridge(self.t_h1,ControlService(self.h1_store))
        self.executor=ExecutorBridge(self.t_h2,RunSemantics(self.h2_store),'hermes-2')
        self.qa=QABridge(self.t_qa,'isolated-qa')

    def tearDown(self): self.h1_store.close(); self.h2_store.close(); self.tmp.cleanup()

    def test_full_machine_chain_reaches_pass(self):
        task=TaskEnvelope('1.0','TASK_ENVELOPE','t1','p1','corr1','hermes-1',1,'idem1',now_iso(),'safe deterministic task',(
            AcceptanceCriterion('A1','artifact generated'),AcceptanceCriterion('A2','no side effects')
        ))
        self.director.dispatch(task)
        def execute(t): return ('SUCCEEDED',('artifact://result',),{'A1':True,'A2':True})
        self.executor.process('t1','r1',execute)
        self.director.observe_ack('t1','r1')
        self.director.observe_result('t1','r1')
        def review(t,r): return ('PASS',{'A1':True,'A2':True},('evidence://qa',))
        self.qa.review('t1','r1','q1',review)
        self.director.observe_qa('t1','r1','q1')
        self.assertEqual(self.director.control.snapshot('t1')['state'],'PASS')
        self.assertEqual(self.director.control.events('t1')[-1]['event_type'],'QA_PASS')


if __name__=='__main__': unittest.main()
