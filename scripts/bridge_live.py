#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.bridge_polling import H1PollingCollector, H2PollingWorker, PROOF_OBJECTIVE, PROOF_PROJECT, QAPollingWorker
from runtime.bridge_roles import DirectorBridge, ExecutorBridge, QABridge
from runtime.control_service import ControlService
from runtime.envelopes import AcceptanceCriterion, TaskEnvelope, now_iso
from runtime.execution_store import ExecutionStore
from runtime.git_bridge import GitBridgeTransport
from runtime.run_semantics import RunSemantics


def transport(args) -> GitBridgeTransport:
    t = GitBridgeTransport(args.worktree, branch=args.branch, artifact_dir=args.artifact_dir)
    if args.git_name and args.git_email:
        t.configure_identity(args.git_name, args.git_email)
    return t


def h1_dispatch(args) -> dict:
    t = transport(args)
    store = ExecutionStore(args.db)
    try:
        director = DirectorBridge(t, ControlService(store))
        task = TaskEnvelope(
            '1.0', 'TASK_ENVELOPE', args.task_id, PROOF_PROJECT, args.correlation_id,
            'hermes-1', 1, args.idempotency_key, now_iso(), PROOF_OBJECTIVE,
            (
                AcceptanceCriterion('A1', 'Task/ACK/Result/QA correlation chain is valid'),
                AcceptanceCriterion('A2', 'Duplicate/replay is rejected'),
                AcceptanceCriterion('A3', 'Missed heartbeat fails closed'),
            ),
        )
        commit = director.dispatch(task)
        return {'role': 'h1', 'action': 'dispatch', 'task_id': task.task_id, 'commit': commit, 'state': director.control.snapshot(task.task_id)['state']}
    finally:
        store.close()


def h2_once(args) -> dict:
    t = transport(args)
    store = ExecutionStore(args.db)
    try:
        worker = H2PollingWorker(t, ExecutorBridge(t, RunSemantics(store), 'hermes-2'))
        processed = worker.process_once()
        return {'role': 'h2', 'action': 'poll-once', 'processed': processed}
    finally:
        store.close()


def qa_once(args) -> dict:
    t = transport(args)
    worker = QAPollingWorker(t, QABridge(t, 'isolated-qa'))
    return {'role': 'qa', 'action': 'poll-once', 'processed': worker.process_once()}


def h1_collect(args) -> dict:
    t = transport(args)
    store = ExecutionStore(args.db)
    try:
        director = DirectorBridge(t, ControlService(store))
        collector = H1PollingCollector(t, director)
        completed = collector.collect_once()
        payload = {'role': 'h1', 'action': 'collect-once', 'completed': completed}
        if args.task_id:
            payload['task'] = director.control.snapshot(args.task_id)
            payload['events'] = director.control.events(args.task_id)
        return payload
    finally:
        store.close()


def status(args) -> dict:
    store = ExecutionStore(args.db)
    try:
        svc = ControlService(store)
        return {'task': svc.snapshot(args.task_id), 'events': svc.events(args.task_id)}
    finally:
        store.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='AI OS harmless bridge proof runner')
    p.add_argument('--worktree', help='Dedicated bridge Git worktree')
    p.add_argument('--db', required=True, help='Node-local execution SQLite path')
    p.add_argument('--branch', default='main')
    p.add_argument('--artifact-dir', default='control_artifacts')
    p.add_argument('--git-name')
    p.add_argument('--git-email')
    sub = p.add_subparsers(dest='command', required=True)

    d = sub.add_parser('h1-dispatch')
    d.add_argument('--task-id', required=True)
    d.add_argument('--correlation-id', required=True)
    d.add_argument('--idempotency-key', required=True)

    sub.add_parser('h2-once')
    sub.add_parser('qa-once')

    c = sub.add_parser('h1-collect')
    c.add_argument('--task-id')

    s = sub.add_parser('status')
    s.add_argument('--task-id', required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    if args.command != 'status' and not args.worktree:
        parser().error('--worktree is required for bridge operations')
    handlers = {
        'h1-dispatch': h1_dispatch,
        'h2-once': h2_once,
        'qa-once': qa_once,
        'h1-collect': h1_collect,
        'status': status,
    }
    result = handlers[args.command](args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
