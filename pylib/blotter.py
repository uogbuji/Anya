'''Append-only log for user review. Never modified, only appended.
Uses file locking for shared context with other agent systems.'''

from datetime import UTC, datetime
from pathlib import Path

from anya._locking import StateLockError, locked


class BlotterLockError(StateLockError):
    '''Raised when the blotter lock cannot be acquired within the timeout.'''


def append_blotter(blotter_path: Path, job_id: str, entry: str) -> None:
    '''
    Append an entry to the blotter. Format: timestamp, job_id, entry.
    Uses exclusive file lock; raises BlotterLockError if lock cannot be
    acquired within the configured timeout (config.toml [blotter] lock_timeout).
    '''
    with locked(blotter_path, BlotterLockError):
        ts = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        with blotter_path.open('a', encoding='utf-8') as f:
            f.write(f'[{ts}] [{job_id}] {entry}\n')


def read_blotter(blotter_path: Path, limit: int = 100) -> list[str]:
    '''Read the last N lines of the blotter. Loads the whole file; see read_blotter_tail for large ones.'''
    if not blotter_path.exists():
        return []
    lines = blotter_path.read_text(encoding='utf-8').strip().splitlines()
    return lines[-limit:] if limit else lines


def read_blotter_tail(blotter_path: Path, limit: int = 50) -> list[str]:
    '''Read the last N lines efficiently (from at most the final 64KB), for large blotters.'''
    if not blotter_path.exists():
        return []
    size = blotter_path.stat().st_size
    if size == 0:
        return []
    read_size = min(65536, size)  # 64KB tail
    with blotter_path.open('rb') as f:
        f.seek(-read_size, 2)
        tail = f.read().decode('utf-8', errors='replace')
    if read_size < size:
        first_nl = tail.find('\n')
        if first_nl >= 0:
            tail = tail[first_nl + 1:]
    lines = tail.splitlines()
    return lines[-limit:] if len(lines) > limit else lines
