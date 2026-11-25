'''
Long-term memory: findings a job asks to keep across runs.

A controller adds entries by printing ---MEMORY--- ... ---END MEMORY--- and removes its
own entries by printing ---RESOLVED--- ... ---END RESOLVED---; the executor applies both.
Controllers can read memory through read_memory() (the executor passes the file path as
ANYA_MEMORY_FILE).

File format, one entry per job finding:

    ---
    [2026-11-24T09:30:00.000000Z] [job-id]
    content, any number of lines (a bare `---` line inside content is fine)

Writes hold the same kind of exclusive file lock as the blotter.
'''

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from anya._locking import StateLockError, locked

MEMORY_FILE_ENV = 'ANYA_MEMORY_FILE'

_HEADER_RE = re.compile(r'^\[([^\]\n]+)\] \[([^\]\n]+)\]$')
# An entry starts at a `---` line followed by a header line; other `---` lines are content.
_ENTRY_SPLIT_RE = re.compile(r'(?m)^---\n(?=\[[^\]\n]+\] \[[^\]\n]+\]$)')
_MIN_PHRASE_LEN = 8  # shorter resolved lines ("done", "fixed") would match too much


class MemoryLockError(StateLockError):
    '''Raised when the memory file's lock cannot be acquired within the timeout.'''


@dataclass(frozen=True)
class MemoryEntry:
    timestamp: str
    job_id: str
    content: str


def parse_memory(text: str) -> tuple[str, list[MemoryEntry]]:
    '''
    Split memory text into (preamble, entries). Text that isn't part of a well-formed
    entry (e.g. hand-written notes at the top) is returned as the preamble, untouched.
    '''
    parts = _ENTRY_SPLIT_RE.split(text)
    preamble = parts[0].strip()
    entries = []
    for part in parts[1:]:
        header, _, content = part.partition('\n')
        m = _HEADER_RE.match(header)
        entries.append(MemoryEntry(m[1], m[2], content.strip()))
    return preamble, entries


def format_memory(preamble: str, entries: list[MemoryEntry]) -> str:
    '''Inverse of parse_memory.'''
    head = f'{preamble}\n' if preamble else ''
    return head + ''.join(f'\n---\n[{e.timestamp}] [{e.job_id}]\n{e.content}\n' for e in entries)


def memory_path_from_env() -> Path | None:
    '''The memory file the executor gave this controller, if any.'''
    env = os.environ.get(MEMORY_FILE_ENV)
    return Path(env) if env else None


def read_memory(memory_path: Path | None = None, *, job_id: str | None = None) -> str:
    '''
    Read memory as text. memory_path defaults to $ANYA_MEMORY_FILE (set for controllers).
    With job_id, return only that job's entries (e.g. job_id=os.environ['ANYA_JOB_ID']).
    '''
    path = memory_path or memory_path_from_env()
    if path is None or not path.exists():
        return ''
    text = path.read_text(encoding='utf-8')
    if job_id is None:
        return text
    _, entries = parse_memory(text)
    return format_memory('', [e for e in entries if e.job_id == job_id]).strip()


def append_memory(memory_path: Path, job_id: str, content: str) -> None:
    '''Append an entry for job_id. Raises MemoryLockError if the lock times out.'''
    ts = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
    with locked(memory_path, MemoryLockError), memory_path.open('a', encoding='utf-8') as f:
        f.write(f'\n---\n[{ts}] [{job_id}]\n{content}\n')


def resolved_phrases(resolved_description: str) -> list[str]:
    '''
    The phrases a ---RESOLVED--- block names: one per non-empty line (list bullets
    stripped), lowercased, skipping lines too short to identify an entry safely.
    '''
    phrases = (line.strip().lstrip('-*•').strip().lower() for line in resolved_description.splitlines())
    return [p for p in phrases if len(p) >= _MIN_PHRASE_LEN]


def prune_memory(memory_path: Path, resolved_description: str, job_id: str) -> int:
    '''
    Remove job_id's memory entries whose content contains any resolved phrase
    (case-insensitive). Entries from other jobs are never touched. Returns the number
    removed. Raises MemoryLockError if the lock times out.
    '''
    phrases = resolved_phrases(resolved_description)
    if not phrases or not memory_path.exists():
        return 0
    with locked(memory_path, MemoryLockError):
        preamble, entries = parse_memory(memory_path.read_text(encoding='utf-8'))

        def resolved(e: MemoryEntry) -> bool:
            return e.job_id == job_id and any(p in e.content.lower() for p in phrases)

        kept = [e for e in entries if not resolved(e)]
        removed = len(entries) - len(kept)
        if removed:
            memory_path.write_text(format_memory(preamble, kept), encoding='utf-8')
    structlog.get_logger().info('pruned resolved memory entries', job_id=job_id, removed=removed)
    return removed
