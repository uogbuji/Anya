'''Exclusive file locks for anya's shared state files (blotter, memory).'''

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from anya.config import get_config


class StateLockError(Exception):
    '''A state file's lock could not be acquired within the configured timeout.'''


def lock_path(path: Path) -> Path:
    '''The lock file beside a state file, e.g. blotter.txt → blotter.txt.lock.'''
    return path.with_name(path.name + '.lock')


@contextmanager
def locked(path: Path, error: type[StateLockError] = StateLockError) -> Iterator[None]:
    '''
    Hold the exclusive lock for `path` (timeout: config.toml [blotter] lock_timeout,
    default 30s), creating the parent dir if needed. Raises `error` on timeout.
    '''
    timeout = get_config().blotter_lock_timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lock_path(path), timeout=timeout):
            yield
    except Timeout as e:
        raise error(
            f'Could not acquire the lock for {path} within {timeout:.0f}s. Another process may be '
            f'using it. Investigate a stale lock at {lock_path(path)}'
        ) from e
