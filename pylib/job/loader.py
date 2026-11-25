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
    frequency   = "daily"        # daily | weekday | weekly (Mondays) | saturday | sunday
    phase       = "default"      # default | ignore
    entry       = "controller.py"
    type        = "pymain"       # only pymain is implemented today
    prompts     = "anya.loom.toml"  # optional
    id          = "..."          # optional; overrides dir name
    select      = 3              # optional; exposed as ANYA_JOB_SELECT
'''

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import structlog
from dotenv import dotenv_values

from anya.job.runs import is_due, normalize_frequency


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
    try:
        frequency = normalize_frequency(str(data.get('frequency') or 'daily'))
    except ValueError as e:
        raise ValueError(f'Job {job_id!r}: {e}') from None
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


def filter_by_job_ids(
    jobs: list[Job],
    *,
    select: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[Job]:
    '''
    Filter jobs by id. select limits to listed ids; exclude removes listed ids.
    Applied after phase filtering.
    '''
    result = jobs
    if select:
        result = [j for j in result if j.id in select]
    if exclude:
        result = [j for j in result if j.id not in exclude]
    return result


def discover_jobs(job_dir: Path, *, errors: list[tuple[str, str]] | None = None) -> list[Job]:
    '''
    Discover all jobs in job_dir. Each subdir with anya.toml is a job.

    A job that fails to load (bad TOML, missing entry file, unsupported type) is
    logged and skipped, so one broken job can't stop the others. Pass an `errors`
    list to also collect (dir_name, message) for each failure, e.g. to report it.
    '''
    jobs: list[Job] = []
    if not job_dir.exists():
        return jobs
    for entry in sorted(job_dir.iterdir()):
        # `.`-prefixed dirs are hidden; `_`-prefixed dirs (e.g. `_lib/`) are
        # shared code referenced by controllers, not jobs themselves.
        if not entry.is_dir() or entry.name.startswith(('.', '_')):
            continue
        try:
            job = load_job(entry)
        except Exception as e:  # noqa: BLE001 — isolate each job's load failure
            structlog.get_logger().error('job failed to load; skipping', job_dir=str(entry), error=str(e))
            if errors is not None:
                errors.append((entry.name, f'{type(e).__name__}: {e}'))
            continue
        if job:
            jobs.append(job)
    return jobs


def should_run_job(job: Job, now: datetime | None = None, last_run: date | None = None) -> bool:
    '''
    Whether a job is due this tick, given the date it last ran (None if never/unknown).
    See anya.job.runs for the rule: due when it hasn't run since its most recent
    scheduled date, so missed runs catch up and repeat ticks don't re-run.
    '''
    today = (now or datetime.now()).date()
    return is_due(job.frequency, today, last_run)
