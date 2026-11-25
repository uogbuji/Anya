'''
When a job is due, and the record of when each job last ran.

Each frequency has an *anchor*: the most recent date, on or before today, on which the
job is scheduled. A job is due when it hasn't run since its anchor. So:

- A missed run (scheduler drift past midnight, downtime, a failed tick) happens at the
  next tick, instead of waiting a whole period.
- A restart, or an extra tick, on a day a job already ran doesn't run it again.
- With no record yet, a job is due only on a scheduled day (anchor == today), the same
  rule as before run records existed, so adding the record doesn't trigger a burst of runs.

Dates are local dates (the process's time zone; containers default to UTC unless TZ is set).

The date logic here is pure; load_runs / record_run are the only I/O.
'''

import json
import os
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import structlog


# frequency → (today → most recent scheduled date on or before today)
ANCHORS: dict[str, Callable[[date], date]] = {
    'daily': lambda d: d,
    'weekday': lambda d: d - timedelta(days=max(0, d.weekday() - 4)),  # Sat/Sun → Friday
    'weekly': lambda d: d - timedelta(days=d.weekday()),  # Monday
    'saturday': lambda d: d - timedelta(days=(d.weekday() - 5) % 7),
    'sunday': lambda d: d - timedelta(days=(d.weekday() - 6) % 7),
}

# Accepted spellings in anya.toml → canonical frequency
ALIASES: dict[str, str] = {
    'weekdays': 'weekday',
    'saturdays': 'saturday',
    'sundays': 'sunday',
    'monday': 'weekly',
    'mondays': 'weekly',
}


def normalize_frequency(raw: str) -> str:
    '''Canonical frequency name for an anya.toml value; ValueError if unknown.'''
    freq = raw.strip().lower()
    freq = ALIASES.get(freq, freq)
    if freq not in ANCHORS:
        raise ValueError(f'unknown frequency {raw!r}; use one of {sorted(ANCHORS)} (aliases: {sorted(ALIASES)})')
    return freq


def is_due(frequency: str, today: date, last_run: date | None) -> bool:
    '''Whether a job with this (canonical) frequency should run today, given its last run date.'''
    anchor = ANCHORS[frequency](today)
    if last_run is None:
        return anchor == today
    return last_run < anchor


def load_runs(path: Path) -> dict[str, dict]:
    '''
    Read the run record: {job_id: {'last_run': ISO datetime, 'status': 'ok' | 'failed'}}.
    A missing file is an empty record. An unreadable one is logged and treated as empty,
    which means only the scheduled-day rule applies until the next run rewrites it.
    '''
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        structlog.get_logger().warning('job run record unreadable; ignoring it', path=str(path), error=str(e))
        return {}
    return data if isinstance(data, dict) else {}


def last_run_date(runs: dict[str, dict], job_id: str) -> date | None:
    '''The local date a job last ran, from a loaded run record, or None.'''
    try:
        return datetime.fromisoformat(runs[job_id]['last_run']).astimezone().date()
    except (KeyError, TypeError, ValueError):
        return None


def record_run(path: Path, runs: dict[str, dict], job_id: str, when: datetime, status: str) -> None:
    '''
    Update `runs` in place for one job and write the whole record atomically
    (temp file + rename), so a crash mid-write can't leave a truncated file.
    '''
    runs[job_id] = {'last_run': when.astimezone().isoformat(timespec='seconds'), 'status': status}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(runs, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)
