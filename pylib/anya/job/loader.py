'''
Job loader: discover jobs from job/ dir, parse anya.toml, .env, frequency.

A job dir layout:

    job/my-job/
      anya.toml      # job metadata
      controller.py  # entry point (default name; override via anya.toml entry=)
      anya.loom.toml # prompts (default name; override via anya.toml prompts=)
      .env           # optional per-job env

anya.toml fields:

    title       = "..."          # informational
    description = "..."          # informational
    frequency   = "daily"        # daily | weekly | sundays | saturday | weekday
    phase       = "default"      # default | ignore
    entry       = "controller.py"
    type        = "pymain"       # only pymain is implemented today
    prompts     = "anya.loom.toml"  # optional
    id          = "..."          # optional; overrides dir name
    select      = 3              # optional; exposed as ANYA_JOB_SELECT
'''

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values


_VALID_TYPES = frozenset({'pymain'})


@dataclass
class Job:
    '''A single job definition.'''

    id: str
    path: Path
    title: str
    description: str
    frequency: str
    phase: str
    entry: Path
    type: str
    prompts: Path
    env: dict[str, str]
    select: int | None


def load_job(path: Path) -> Job | None:
    '''
    Load a single job from a directory. Returns None if anya.toml missing.
    '''
    toml_file = path / 'anya.toml'
    if not toml_file.exists():
        return None
    with toml_file.open('rb') as f:
        data = tomllib.load(f)

    job_id = str(data.get('id') or path.name).strip() or path.name
    title = str(data.get('title') or job_id)
    description = str(data.get('description') or '')
    frequency = str(data.get('frequency') or 'daily').strip().lower() or 'daily'
    phase = str(data.get('phase') or 'default').strip().lower() or 'default'
    entry_name = str(data.get('entry') or 'controller.py')
    type_ = str(data.get('type') or 'pymain').strip().lower()
    prompts_name = str(data.get('prompts') or 'anya.loom.toml')

    if type_ not in _VALID_TYPES:
        raise ValueError(
            f'Job {job_id!r}: unsupported type {type_!r}. Supported: {sorted(_VALID_TYPES)}'
        )

    entry = path / entry_name
    if not entry.exists():
        raise FileNotFoundError(f'Job {job_id!r}: entry file not found: {entry}')

    prompts = path / prompts_name

    select_raw = data.get('select')
    if isinstance(select_raw, int):
        select: int | None = select_raw
    elif isinstance(select_raw, str) and select_raw.strip().isdigit():
        select = int(select_raw.strip())
    else:
        select = None

    env_file = path / '.env'
    env = dict(dotenv_values(env_file)) if env_file.exists() else {}
    env = {k: str(v) for k, v in env.items() if v is not None}

    return Job(
        id=job_id,
        path=path,
        title=title,
        description=description,
        frequency=frequency,
        phase=phase,
        entry=entry,
        type=type_,
        prompts=prompts,
        env=env,
        select=select,
    )


def filter_by_phase(jobs: list[Job], phases: set[str]) -> list[Job]:
    '''Include only jobs whose phase is in phases.'''
    return [j for j in jobs if j.phase in phases]


def discover_jobs(job_dir: Path) -> list[Job]:
    '''
    Discover all jobs in job_dir. Each subdir with anya.toml is a job.
    '''
    jobs: list[Job] = []
    if not job_dir.exists():
        return jobs
    for entry in sorted(job_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith('.'):
            job = load_job(entry)
            if job:
                jobs.append(job)
    return jobs


def should_run_job(job: Job, now: datetime | None = None) -> bool:
    '''
    Per-job frequency check. Main schedule sets granularity (e.g. daily);
    this filters which jobs run this tick.
    '''
    now = now or datetime.now()
    freq = job.frequency.lower()
    if freq == 'daily':
        return True
    if freq == 'weekly':
        return now.weekday() == 0  # Monday
    if freq == 'sundays':
        return now.weekday() == 6
    if freq == 'saturday':
        return now.weekday() == 5
    if freq.startswith('weekday'):
        return now.weekday() < 5
    return True  # unknown -> run
