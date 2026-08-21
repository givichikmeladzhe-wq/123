#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path


def mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def fingerprint(path: Path) -> str | None:
    tool = shutil.which('ssh-keygen')
    if not tool or not path.is_file():
        return None
    proc = subprocess.run([tool, '-lf', str(path)], text=True, capture_output=True)
    if proc.returncode != 0:
        pub = path.with_suffix(path.suffix + '.pub') if path.suffix else Path(str(path) + '.pub')
        if pub.is_file():
            proc = subprocess.run([tool, '-lf', str(pub)], text=True, capture_output=True)
    if proc.returncode != 0:
        return None
    fields = proc.stdout.strip().split()
    return fields[1] if len(fields) > 1 else None


def inspect_path(raw: str) -> dict:
    p = Path(raw).expanduser()
    item = {'path': str(p), 'exists': p.exists()}
    if not p.exists():
        return item
    st = p.stat()
    item.update({'mode': mode(p), 'uid': st.st_uid, 'gid': st.st_gid, 'type': 'dir' if p.is_dir() else 'file'})
    fp = fingerprint(p)
    if fp:
        item['fingerprint'] = fp
    return item


def service_candidates() -> list[dict]:
    systemctl = shutil.which('systemctl')
    if not systemctl:
        return []
    proc = subprocess.run(
        [systemctl, 'list-units', '--type=service', '--all', '--no-legend', '--no-pager'],
        text=True, capture_output=True
    )
    if proc.returncode != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        if 'hermes' not in line.lower():
            continue
        fields = line.split(None, 4)
        if fields:
            out.append({'unit': fields[0], 'load': fields[1] if len(fields)>1 else None,
                        'active': fields[2] if len(fields)>2 else None,
                        'sub': fields[3] if len(fields)>3 else None})
    return out


def env_names() -> list[str]:
    needles = ('HERMES', 'BRIDGE', 'SSH', 'SFTP', 'GIT', 'CONTROL')
    return sorted(k for k in os.environ if any(n in k.upper() for n in needles))


def main() -> int:
    p = argparse.ArgumentParser(description='Read-only Hermes bridge discovery; never prints secret values')
    p.add_argument('--candidate-id', default='bridge-candidate-01')
    p.add_argument('--transport', choices=['SFTP', 'GIT_OVER_SSH', 'UNKNOWN'], default='UNKNOWN')
    p.add_argument('--path', action='append', default=[], help='Known candidate path/key/env/known_hosts path; metadata only')
    p.add_argument('--bridge-path', help='Dedicated bridge directory/worktree to inspect')
    p.add_argument('--output', help='Optional JSON evidence output path')
    args = p.parse_args()

    paths = list(args.path)
    if args.bridge_path:
        paths.append(args.bridge_path)

    evidence = {
        'candidate_id': args.candidate_id,
        'host_identity': socket.gethostname(),
        'runtime_user': getpass.getuser(),
        'transport_declared': args.transport,
        'environment_variable_names_only': env_names(),
        'candidate_paths': [inspect_path(x) for x in paths],
        'hermes_services': service_candidates(),
        'secret_values_emitted': False,
    }

    existing = [x for x in evidence['candidate_paths'] if x.get('exists')]
    bridge_ok = True
    if args.bridge_path:
        bp = Path(args.bridge_path).expanduser()
        bridge_ok = bp.exists() and bp.is_dir()
    service_ok = bool(evidence['hermes_services'])
    evidence['result'] = 'DISCOVERED_LOCAL_FACTS' if (existing or service_ok) and bridge_ok else 'UNVERIFIED'
    evidence['note'] = 'Local read-only facts only; authenticated peer reachability and authorization require a separate read-only transport probe.'

    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if args.output:
        Path(args.output).write_text(payload, encoding='utf-8')
    print(payload, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
