from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from runtime.execution_enforcement import EnforcementError


ALLOWED_KINDS = {'tasks', 'acks', 'runs', 'results', 'qa', 'evidence', 'events'}


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


class ArtifactRepository:
    """Immutable filesystem boundary for versioned control artifacts.

    It is intentionally transport-agnostic: the directory may live in a Git
    worktree, while this class only enforces safe paths, immutable writes and
    content-addressable evidence.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for kind in ALLOWED_KINDS:
            (self.root / kind).mkdir(exist_ok=True)

    def put(self, kind: str, artifact_id: str, payload: dict[str, Any]) -> dict[str, str | bool]:
        if kind not in ALLOWED_KINDS:
            raise EnforcementError(f'artifact kind not allowed: {kind}')
        self._validate_id(artifact_id)
        data = canonical_bytes(payload)
        digest = hashlib.sha256(data).hexdigest()
        directory = self.root / kind
        path = directory / f'{artifact_id}.json'
        digest_path = directory / f'{artifact_id}.sha256'

        if path.exists():
            existing = path.read_bytes()
            if existing != data:
                raise EnforcementError('immutable artifact conflict')
            existing_digest = hashlib.sha256(existing).hexdigest()
            if existing_digest != digest:
                raise EnforcementError('artifact digest mismatch')
            return {'created': False, 'path': str(path), 'sha256': digest}

        tmp = directory / f'.{artifact_id}.{os.getpid()}.tmp'
        tmp.write_bytes(data)
        os.replace(tmp, path)
        digest_path.write_text(f'{digest}  {path.name}\n', encoding='utf-8')
        return {'created': True, 'path': str(path), 'sha256': digest}

    def get(self, kind: str, artifact_id: str) -> dict[str, Any]:
        if kind not in ALLOWED_KINDS:
            raise EnforcementError(f'artifact kind not allowed: {kind}')
        self._validate_id(artifact_id)
        path = self.root / kind / f'{artifact_id}.json'
        if not path.exists():
            raise EnforcementError('artifact not found')
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        digest_path = path.with_suffix('.sha256')
        if not digest_path.exists() or not digest_path.read_text(encoding='utf-8').startswith(digest):
            raise EnforcementError('artifact integrity check failed')
        return json.loads(data.decode('utf-8'))

    def verify(self, kind: str, artifact_id: str) -> str:
        self.get(kind, artifact_id)
        path = self.root / kind / f'{artifact_id}.json'
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {'.', '..'}:
            raise EnforcementError('invalid artifact id')
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:' for c in value):
            raise EnforcementError('unsafe artifact id')
        if '/' in value or '\\' in value:
            raise EnforcementError('unsafe artifact path')
