#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
from pathlib import Path

GATE = 'OWNER_GATE_BRIDGE_01_APPROVED'
ROLES = {'h1', 'h2', 'qa'}


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, text=True)


def build_plan(args) -> dict:
    base = Path(args.base).expanduser().resolve()
    worktree = base / 'control-repo'
    state = base / 'state'
    return {
        'role': args.role,
        'runtime_user': getpass.getuser(),
        'base': str(base),
        'worktree': str(worktree),
        'state_dir': str(state),
        'db': str(state / f'{args.role}-execution.sqlite3'),
        'repo_url': args.repo,
        'branch': args.branch,
        'actions': [
            'verify non-root dedicated runtime identity',
            'create role-local base/state directories',
            'clone or fast-forward dedicated control repository',
            'configure repository-local Git identity',
            'run read-only bridge discovery probe',
        ],
        'prohibited': [
            'create/change SSH keys', 'change firewall', 'change Xray', 'change Telegram',
            'touch product repositories', 'read/print secrets', 'open shell/forwarding permissions',
        ],
        'requires_gate_for_apply': GATE,
    }


def apply(args, plan: dict) -> dict:
    if not args.execute:
        raise SystemExit('refusing mutation: add --execute')
    if os.environ.get('AI_OS_OWNER_GATE') != GATE:
        raise SystemExit(f'refusing mutation: AI_OS_OWNER_GATE must equal {GATE}')
    if os.geteuid() == 0:
        raise SystemExit('refusing bridge bootstrap as root; use dedicated non-root transport identity')
    if args.expected_user and getpass.getuser() != args.expected_user:
        raise SystemExit('runtime identity does not match --expected-user')

    base = Path(plan['base']); worktree = Path(plan['worktree']); state = Path(plan['state_dir'])
    base.mkdir(parents=True, exist_ok=True); state.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700); os.chmod(state, 0o700)

    if worktree.exists():
        if not (worktree / '.git').exists():
            raise SystemExit('existing worktree path is not a Git repository')
        run(['git','fetch','origin',args.branch],cwd=worktree)
        run(['git','checkout',args.branch],cwd=worktree)
        run(['git','merge','--ff-only',f'origin/{args.branch}'],cwd=worktree)
    else:
        run(['git','clone','--branch',args.branch,'--single-branch',args.repo,str(worktree)])

    run(['git','config','user.name',args.git_name],cwd=worktree)
    run(['git','config','user.email',args.git_email],cwd=worktree)

    discovery = subprocess.run(
        [shutil.which('python3') or 'python3', str(worktree/'scripts'/'bridge_discovery.py'),
         '--candidate-id', f'{args.role}-local-runtime', '--transport', 'GIT_OVER_SSH', '--bridge-path', str(worktree)],
        text=True, capture_output=True, check=True,
    )
    evidence = json.loads(discovery.stdout)
    return {**plan, 'applied': True, 'discovery': evidence}


def main() -> int:
    p=argparse.ArgumentParser(description='Gate-enforced bridge node bootstrap')
    p.add_argument('command',choices=['plan','apply'])
    p.add_argument('--role',choices=sorted(ROLES),required=True)
    p.add_argument('--base',required=True)
    p.add_argument('--repo',default='https://github.com/givichikmeladzhe-wq/123.git')
    p.add_argument('--branch',default='main')
    p.add_argument('--git-name',required=True)
    p.add_argument('--git-email',required=True)
    p.add_argument('--expected-user')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--output')
    args=p.parse_args()
    plan=build_plan(args)
    result=plan if args.command=='plan' else apply(args,plan)
    payload=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if args.output: Path(args.output).write_text(payload,encoding='utf-8')
    print(payload,end='')
    return 0


if __name__=='__main__': raise SystemExit(main())
