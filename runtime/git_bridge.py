from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from runtime.artifact_repository import ALLOWED_KINDS, ArtifactRepository
from runtime.execution_enforcement import EnforcementError


class GitBridgeTransport:
    """Versioned control-artifact transport over a dedicated Git worktree.

    Authentication/SSH restrictions are intentionally external configuration;
    this class never reads or logs credentials. It only performs ff-only sync,
    immutable artifact writes, commits and pushes to one configured branch.
    """

    def __init__(self, worktree: str | Path, *, branch: str = 'main', artifact_dir: str = 'control_artifacts') -> None:
        self.worktree = Path(worktree).resolve()
        self.branch = branch
        self.artifact_dir = artifact_dir
        if not (self.worktree / '.git').exists():
            raise EnforcementError('bridge worktree is not a git repository')
        self.artifacts = ArtifactRepository(self.worktree / artifact_dir)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(['git', *args], cwd=self.worktree, text=True, capture_output=True)
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ['git command failed']
            raise EnforcementError(f'git transport error: {detail[0]}')
        return proc

    def configure_identity(self, name: str, email: str) -> None:
        if not name or not email:
            raise EnforcementError('git identity required')
        self._git('config', 'user.name', name)
        self._git('config', 'user.email', email)

    def sync(self) -> str:
        self._git('fetch', 'origin', self.branch)
        self._git('checkout', self.branch)
        self._git('merge', '--ff-only', f'origin/{self.branch}')
        return self.head()

    def publish(self, kind: str, artifact_id: str, payload: dict[str, Any], *, message: str) -> dict[str, Any]:
        self.sync()
        result = self.artifacts.put(kind, artifact_id, payload)
        if result['created']:
            rel_json = Path(result['path']).relative_to(self.worktree)
            rel_sha = rel_json.with_suffix('.sha256')
            self._git('add', '--', str(rel_json), str(rel_sha))
            self._git('commit', '-m', message)
            self._git('push', 'origin', f'HEAD:{self.branch}')
        return {**result, 'commit': self.head()}

    def read(self, kind: str, artifact_id: str) -> dict[str, Any]:
        self.sync()
        return self.artifacts.get(kind, artifact_id)

    def list_ids(self, kind: str) -> list[str]:
        if kind not in ALLOWED_KINDS:
            raise EnforcementError(f'artifact kind not allowed: {kind}')
        self.sync()
        directory = self.worktree / self.artifact_dir / kind
        if not directory.exists():
            return []
        return sorted(p.stem for p in directory.glob('*.json') if p.is_file())

    def exists(self, kind: str, artifact_id: str) -> bool:
        return artifact_id in set(self.list_ids(kind))

    def head(self) -> str:
        return self._git('rev-parse', 'HEAD').stdout.strip()
