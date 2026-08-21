import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'bridge_live.py'
DISCOVERY = ROOT / 'scripts' / 'bridge_discovery.py'


def git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, check=True, text=True, capture_output=True)


class BridgeLiveCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.bare=root/'bridge.git'; seed=root/'seed'; self.h1=root/'h1'; self.h2=root/'h2'; self.qa=root/'qa'
        subprocess.run(['git','init','--bare',str(self.bare)],check=True,text=True,capture_output=True)
        subprocess.run(['git','clone',str(self.bare),str(seed)],check=True,text=True,capture_output=True)
        git(seed,'config','user.name','seed'); git(seed,'config','user.email','seed@example.invalid')
        (seed/'README.md').write_text('bridge\n'); git(seed,'add','README.md'); git(seed,'commit','-m','seed'); git(seed,'branch','-M','main'); git(seed,'push','-u','origin','main')
        subprocess.run(['git','--git-dir',str(self.bare),'symbolic-ref','HEAD','refs/heads/main'],check=True,text=True,capture_output=True)
        for p in (self.h1,self.h2,self.qa): subprocess.run(['git','clone',str(self.bare),str(p)],check=True,text=True,capture_output=True)
        self.h1db=root/'h1.sqlite3'; self.h2db=root/'h2.sqlite3'; self.qadb=root/'qa.sqlite3'

    def tearDown(self): self.tmp.cleanup()

    def run_cli(self, worktree, db, name, email, command, *extra):
        cmd=[sys.executable,str(SCRIPT),'--worktree',str(worktree),'--db',str(db),'--git-name',name,'--git-email',email,command,*extra]
        out=subprocess.run(cmd,check=True,text=True,capture_output=True).stdout
        return json.loads(out)

    def test_full_three_node_cli_proof(self):
        d=self.run_cli(self.h1,self.h1db,'hermes-1','h1@example.invalid','h1-dispatch',
                       '--task-id','proof-live-1','--correlation-id','corr-live-1','--idempotency-key','idem-live-1')
        self.assertEqual(d['state'],'ACTIVE_EXECUTION')
        h2=self.run_cli(self.h2,self.h2db,'hermes-2','h2@example.invalid','h2-once')
        self.assertEqual(h2['processed'],['proof-live-1'])
        qa=self.run_cli(self.qa,self.qadb,'isolated-qa','qa@example.invalid','qa-once')
        self.assertEqual(qa['processed'],['run-proof-live-1'])
        h1=self.run_cli(self.h1,self.h1db,'hermes-1','h1@example.invalid','h1-collect','--task-id','proof-live-1')
        self.assertEqual(h1['task']['state'],'PASS')

    def test_discovery_never_prints_secret_value(self):
        env=dict(**__import__('os').environ)
        env['HERMES_BRIDGE_SECRET_TEST']='do-not-leak-this-value'
        proc=subprocess.run([sys.executable,str(DISCOVERY),'--path',str(self.h1)],check=True,text=True,capture_output=True,env=env)
        self.assertIn('HERMES_BRIDGE_SECRET_TEST',proc.stdout)
        self.assertNotIn('do-not-leak-this-value',proc.stdout)
        payload=json.loads(proc.stdout)
        self.assertFalse(payload['secret_values_emitted'])


if __name__=='__main__': unittest.main()
