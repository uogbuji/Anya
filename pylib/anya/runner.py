'''
Main runner: discover jobs, filter by frequency, execute each.
This is the callback for the scheduler.
'''

from datetime import datetime
from pathlib import Path

import structlog

from anya.blotter import append_blotter
from anya.executor import execute_job
from anya.job.loader import discover_jobs, filter_by_phase, should_run_job


async def run_tick(
    job_dir: Path,
    blotter_path: Path,
    memory_path: Path,
    email_to: list[str],
    phases: set[str] | None = None,
) -> None:
    '''
    One tick of the scheduler: run all due jobs.
    phases: include only jobs whose phase is in this set (default: {"default"}).
    '''
    phases = phases or {'default'}
    log = structlog.get_logger()
    jobs = discover_jobs(job_dir)
    jobs = filter_by_phase(jobs, phases)
    now = datetime.now()
    due = [j for j in jobs if should_run_job(j, now)]
    log.info('tick', total_jobs=len(jobs), due=len(due), job_dir=str(job_dir))

    for job in due:
        try:
            await execute_job(
                job,
                blotter_path=blotter_path,
                memory_path=memory_path,
                email_to=email_to,
            )
        except Exception:
            log.exception('job failed', job_id=job.id)
            append_blotter(blotter_path, job.id, f'ERROR: job failed - {job.id}')
