'''Append-only log for user review. Never modified, only appended.'''

from datetime import datetime
from pathlib import Path


def append_blotter(blotter_path: Path, job_id: str, entry: str) -> None:
    '''
    Append an entry to the blotter. Format: timestamp, job_id, entry.
    '''
    blotter_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().isoformat() + 'Z'
    line = f'[{ts}] [{job_id}] {entry}\n'
    with blotter_path.open('a', encoding='utf-8') as f:
        f.write(line)


def read_blotter(blotter_path: Path, limit: int = 100) -> list[str]:
    '''Read last N lines from blotter (for context to Claude).'''
    if not blotter_path.exists():
        return []
    lines = blotter_path.read_text(encoding='utf-8').strip().splitlines()
    return lines[-limit:] if limit else lines
