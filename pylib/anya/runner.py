'''
Main runner: discover jobs, filter by frequency, execute each.
This is the callback for the scheduler.
'''

from datetime import datetime
from pathlib import Path

import structlog

from anya.blotter import BlotterLockError, append_blotter
from anya.email_unosend import send_email
from anya.executor import execute_job
from anya.job.loader import discover_jobs, filter_by_phase, should_run_job
from anya.llm import LLMConfig


async def run_tick(
    job_dir: Path,
    blotter_path: Path,
    memory_path: Path,
    email_to: list[str],
    phases: set[str] | None = None,
    llm_config: LLMConfig | None = None,
) -> None:
    '''
    One tick of the scheduler: run all due jobs.
    phases: include only jobs whose phase is in this set (default: {"default"}).
    Sends one combined email with a section per job (when email_to is set).
    '''
    phases = phases or {'default'}
    log = structlog.get_logger()
    jobs = discover_jobs(job_dir)
    jobs = filter_by_phase(jobs, phases)
    now = datetime.now()
    due = [j for j in jobs if should_run_job(j, now)]
    log.info('tick', total_jobs=len(jobs), due=len(due), job_dir=str(job_dir))

    sections: list[tuple[str, str]] = []  # (job_id, content)
    for job in due:
        try:
            result = await execute_job(
                job,
                blotter_path=blotter_path,
                memory_path=memory_path,
                email_to=email_to,
                llm_config=llm_config,
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
