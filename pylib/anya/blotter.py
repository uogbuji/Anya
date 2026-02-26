'''Append-only log for user review. Never modified, only appended.
Uses file locking for shared context with other agent systems.'''

import os
from datetime import datetime
from pathlib import Path

from filelock import FileLock, Timeout


class BlotterLockError(Exception):
    '''Raised when the blotter lock cannot be acquired within the timeout.'''


def _lock_path(blotter_path: Path) -> Path:
    '''Path for the lock file (beside the blotter).'''
    return blotter_path.with_suffix(blotter_path.suffix + '.lock')


def _lock_timeout() -> float:
    '''Lock timeout in seconds (BLOTTER_LOCK_TIMEOUT env, default 30).'''
    try:
        return float(os.environ.get('BLOTTER_LOCK_TIMEOUT', '30'))
    except ValueError:
        return 30.0


def append_blotter(blotter_path: Path, job_id: str, entry: str) -> None:
    '''
    Append an entry to the blotter. Format: timestamp, job_id, entry.
    Uses exclusive file lock; raises BlotterLockError if lock cannot be
    acquired within BLOTTER_LOCK_TIMEOUT seconds.
    '''
    lock_path = _lock_path(blotter_path)
    lock = FileLock(lock_path, timeout=_lock_timeout())
    try:
        with lock:
            blotter_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.utcnow().isoformat() + 'Z'
            line = f'[{ts}] [{job_id}] {entry}\n'
            with blotter_path.open('a', encoding='utf-8') as f:
                f.write(line)
    except Timeout as e:
        raise BlotterLockError(
            f'Could not acquire blotter lock within {_lock_timeout():.0f}s. '
            f'Another process may be using {blotter_path}. Investigate stale lock at {lock_path}'
        ) from e


def read_blotter(blotter_path: Path, limit: int = 100) -> list[str]:
    '''Read last N lines from blotter (for context to Claude).'''
    if not blotter_path.exists():
        return []
    lines = blotter_path.read_text(encoding='utf-8').strip().splitlines()
    return lines[-limit:] if limit else lines
