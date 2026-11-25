'''
Main runner: discover jobs, filter by frequency, execute each.
This is the callback for the scheduler.
'''

from datetime import datetime
from pathlib import Path

import structlog

from anya.blotter import BlotterLockError, append_blotter
from anya.email import send_email
from anya.executor import execute_job, report_bodies
from anya.job.loader import discover_jobs, filter_by_job_ids, filter_by_phase, should_run_job
from anya.job.runs import last_run_date, load_runs, record_run


async def run_tick(
    job_dir: Path,
    blotter_path: Path,
    memory_path: Path,
    email_to: list[str],
    phases: set[str] | None = None,
    config_path: Path | None = None,
    select_jobs: set[str] | None = None,
    exclude_jobs: set[str] | None = None,
    runs_path: Path | None = None,
) -> None:
    '''
    One tick of the scheduler: run all due jobs.
    phases: include only jobs whose phase is in this set (default: {"default"}).
    select_jobs: run only these job ids (comma-separated on CLI). Bypasses frequency, and
      these runs aren't recorded, so dev/test runs don't disturb the schedule.
    exclude_jobs: skip these job ids (applied after phase and select filters).
    config_path: path to Anya config.toml (passed through to controllers).
    runs_path: the job run record (anya.job.runs). Each scheduled run, ok or failed, is
      recorded, so a job runs once per period however often ticks come. None: no record,
      so a job is due on each of its scheduled days.
    Sends one combined email with a section per job (when email_to is set).
    '''
    phases = phases or {'default'}
    log = structlog.get_logger()
    load_errors: list[tuple[str, str]] = []
    jobs = discover_jobs(job_dir, errors=load_errors)
    jobs = filter_by_phase(jobs, phases)
    if select_jobs:
        known = {j.id for j in jobs}
        unknown = select_jobs - known
        if unknown:
            log.warning('select_jobs not found', job_ids=sorted(unknown))
    jobs = filter_by_job_ids(jobs, select=select_jobs, exclude=exclude_jobs)
    now = datetime.now()
    runs = load_runs(runs_path) if runs_path else {}
    if select_jobs:
        due = jobs  # explicit selection bypasses frequency for dev/testing
    else:
        due = [j for j in jobs if should_run_job(j, now, last_run_date(runs, j.id))]

    def record(job_id: str, status: str) -> None:
        if not runs_path or select_jobs:
            return
        try:
            record_run(runs_path, runs, job_id, datetime.now(), status)
        except OSError:  # never let bookkeeping fail a job or the tick; worst case it re-runs
            log.exception('could not write job run record', job_id=job_id, path=str(runs_path))
    log.info('tick', total_jobs=len(jobs), due=len(due), job_dir=str(job_dir))

    # A job that couldn't load is reported every tick until fixed, so it can't fail silently.
    # Its id is unknowable (anya.toml may not parse), so select/exclude match its dir name.
    load_errors = [(name, msg) for name, msg in load_errors
                   if (not select_jobs or name in select_jobs) and not (exclude_jobs and name in exclude_jobs)]
    sections: list[tuple[str, str]] = [(name, f'ERROR: job failed to load - {msg}') for name, msg in load_errors]
    for job in due:
        try:
            result = await execute_job(
                job,
                blotter_path=blotter_path,
                memory_path=memory_path,
                email_to=email_to,
                config_path=config_path,
                skip_email=True,
            )
            if result:
                sections.append(result)
            record(job.id, 'ok')
        except Exception as e:
            log.exception('job failed', job_id=job.id)
            record(job.id, 'failed')
            try:
                append_blotter(blotter_path, job.id, f'ERROR: job failed - {job.id}')
            except BlotterLockError as lock_err:
                err_msg = f'**System issue**: {lock_err}\n\nERROR: job failed - {e}'
            else:
                err_msg = f'ERROR: job failed - {e}'
            sections.append((job.id, err_msg))

    if email_to and sections:
        html, text = report_bodies(sections)
        job_ids = ', '.join(jid for jid, _ in sections)
        await send_email(to=email_to, subject=f'[Anya] {job_ids}', html=html, text=text)
