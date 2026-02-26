'''Job loader: discover jobs from job/ dir, parse MAIN.md, .env, frequency.'''

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values


@dataclass
class Job:
    '''A single job definition.'''

    id: str  # dir name, or id: from frontmatter
    path: Path
    main_md: str
    frequency: str  # e.g. 'daily', 'weekly', 'sundays'
    phase: str  # e.g. 'default', 'ignore'; controls --phases filtering
    env: dict[str, str]
    select: int | None  # optional; e.g. how many items to pick (for random-reminders)


def _parse_frequency(main_md: str) -> str:
    '''Extract frequency from MAIN.md. Looks for lines like "frequency: weekly".'''
    for line in main_md.splitlines():
        line = line.strip()
        if line.lower().startswith('frequency:'):
            return line.split(':', 1)[1].strip().lower() or 'daily'
    return 'daily'


def _parse_frontmatter(main_md: str) -> dict[str, str]:
    '''Extract optional YAML-like frontmatter from MAIN.md.'''
    result: dict[str, str] = {}
    if not main_md.strip().startswith('---'):
        return result
    lines = main_md.splitlines()
    i = 1
    while i < len(lines) and lines[i].strip() != '---':
        line = lines[i]
        if ':' in line:
            k, v = line.split(':', 1)
            result[k.strip().lower()] = v.strip()
        i += 1
    return result


def load_job(path: Path) -> Job | None:
    '''
    Load a single job from a directory. Returns None if MAIN.md missing.
    '''
    main_file = path / 'MAIN.md'
    if not main_file.exists():
        return None
    main_md = main_file.read_text(encoding='utf-8')
    fm = _parse_frontmatter(main_md)
    job_id = fm.get('id', path.name).strip() or path.name
    frequency = _parse_frequency(main_md)
    if 'frequency' in fm:
        frequency = fm['frequency']
    phase = fm.get('phase', 'default').strip().lower() or 'default'
    select_raw = fm.get('select', '').strip()
    select = int(select_raw) if select_raw.isdigit() else None
    env_file = path / '.env'
    env = dict(dotenv_values(env_file)) if env_file.exists() else {}
    env = {k: str(v) for k, v in env.items() if v is not None}
    return Job(id=job_id, path=path, main_md=main_md, frequency=frequency, phase=phase, env=env, select=select)


def filter_by_phase(jobs: list[Job], phases: set[str]) -> list[Job]:
    '''Include only jobs whose phase is in phases.'''
    return [j for j in jobs if j.phase in phases]


def discover_jobs(job_dir: Path) -> list[Job]:
    '''
    Discover all jobs in job_dir. Each subdir with MAIN.md is a job.
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
