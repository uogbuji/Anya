'''
Main runner: discover jobs, filter by frequency, execute each.
This is the callback for the scheduler.
'''

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import structlog

from anya.blotter import BlotterLockError, append_blotter
from anya.email import send_email
from anya.executor import execute_job
from anya.job.loader import discover_jobs, filter_by_job_ids, filter_by_phase, should_run_job


async def run_tick(
    job_dir: Path,
    blotter_path: Path,
    memory_path: Path,
    email_to: list[str],
    phases: set[str] | None = None,
    config_path: Path | None = None,
    select_jobs: set[str] | None = None,
    exclude_jobs: set[str] | None = None,
) -> None:
    '''
    One tick of the scheduler: run all due jobs.
    phases: include only jobs whose phase is in this set (default: {"default"}).
    select_jobs: run only these job ids (comma-separated on CLI). Bypasses frequency.
    exclude_jobs: skip these job ids (applied after phase and select filters).
    config_path: path to Anya config.toml (passed through to controllers).
    Sends one combined email with a section per job (when email_to is set).
    '''
    phases = phases or {'default'}
    log = structlog.get_logger()
    jobs = discover_jobs(job_dir)
    jobs = filter_by_phase(jobs, phases)
    if select_jobs:
        known = {j.id for j in jobs}
        unknown = select_jobs - known
        if unknown:
            log.warning('select_jobs not found', job_ids=sorted(unknown))
    jobs = filter_by_job_ids(jobs, select=select_jobs, exclude=exclude_jobs)
    now = datetime.now()
    if select_jobs:
        due = jobs  # explicit selection bypasses frequency for dev/testing
    else:
        due = [j for j in jobs if should_run_job(j, now)]
    log.info('tick', total_jobs=len(jobs), due=len(due), job_dir=str(job_dir))

    sections: list[tuple[str, str]] = []
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
        except Exception as e:
            log.exception('job failed', job_id=job.id)
            try:
                append_blotter(blotter_path, job.id, f'ERROR: job failed - {job.id}')
            except BlotterLockError as lock_err:
                err_msg = f'**System issue**: {lock_err}\n\nERROR: job failed - {e}'
            else:
                err_msg = f'ERROR: job failed - {e}'
            sections.append((job.id, err_msg))

    if email_to and sections:
        html_parts = [f'<h2>Job: {jid}</h2><pre>{content}</pre>' for jid, content in sections]
        text_parts = [f'## Job: {jid}\n\n{content}' for jid, content in sections]
        html = '\n'.join(html_parts)
        text = '\n\n'.join(text_parts)
        job_ids = ', '.join(jid for jid, _ in sections)
        await send_email(to=email_to, subject=f'[Anya] {job_ids}', html=html, text=text)
