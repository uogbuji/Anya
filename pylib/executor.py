'''
Job executor: spawn a controller (D Python program), capture its stdout as
the job's report, route through blotter/memory/email.

The controller is the single boundary that talks to inference() and to any
deterministic side effects. The executor does not call the LLM directly any
more — that lives in the controller's calls to anya.inference.inference().
'''

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import structlog

from anya.blotter import BlotterLockError, append_blotter
from anya.email import send_email
from anya.job.loader import Job
from anya.memory import append_memory, prune_memory


CONTROLLER_TIMEOUT_DEFAULT = 600  # seconds; controllers may do many LLM calls


def _final_error_line(stderr: str) -> str:
    '''
    Pull the most useful single line from a Python traceback in stderr — the
    final non-indented, non-empty line (typically ``ExceptionType: message``).
    Falls back to the last non-blank line if nothing matches.
    '''
    non_empty = [line.rstrip() for line in stderr.splitlines() if line.strip()]
    if not non_empty:
        return '(no stderr)'
    for line in reversed(non_empty):
        if line and not line[0].isspace():
            return line.strip()
    return non_empty[-1].strip()


def _parse_blocks(stdout: str) -> tuple[str, str | None, str | None]:
    '''
    Pull ---MEMORY--- / ---RESOLVED--- blocks out of the controller's stdout.

    Returns (summary, memory_content, resolved_content). Both block types are
    optional. The summary has the blocks stripped.
    '''
    memory_content: str | None = None
    resolved_content: str | None = None

    if '---MEMORY---' in stdout and '---END MEMORY---' in stdout:
        start = stdout.index('---MEMORY---') + len('---MEMORY---')
        end = stdout.index('---END MEMORY---')
        memory_content = stdout[start:end].strip() or None

    if '---RESOLVED---' in stdout and '---END RESOLVED---' in stdout:
        start = stdout.index('---RESOLVED---') + len('---RESOLVED---')
        end = stdout.index('---END RESOLVED---')
        resolved_content = stdout[start:end].strip() or None

    summary = stdout.split('---MEMORY---')[0].split('---RESOLVED---')[0].strip()
    return summary, memory_content, resolved_content


def _add_shared_lib_path(env: dict[str, str], job_path: Path) -> dict[str, str]:
    '''
    If a `_lib/` directory sits alongside the job dir, prepend the jobs-root to
    PYTHONPATH so any controller can `from _lib import ...` shared code. Mutates
    and returns env. Python already puts the controller's own job dir on
    sys.path[0]; this adds the parent so the shared `_lib` package resolves.
    '''
    jobs_root = job_path.resolve().parent
    if (jobs_root / '_lib').is_dir():
        existing = env.get('PYTHONPATH', '')
        parts = [str(jobs_root)] + ([existing] if existing else [])
        env['PYTHONPATH'] = os.pathsep.join(parts)
    return env


async def _run_controller(job: Job, extra_env: dict[str, str], timeout: int) -> tuple[str, str, int]:
    '''
    Spawn the controller as a subprocess. Returns (stdout, stderr, returncode).
    '''
    env = os.environ.copy()
    env.update(job.env)
    env.update(extra_env)
    env['ANYA_JOB_ID'] = job.id
    env['ANYA_JOB_PATH'] = str(job.path.resolve())
    env['ANYA_PROMPTS_FILE'] = str(job.prompts.resolve())
    if job.select is not None:
        env['ANYA_JOB_SELECT'] = str(job.select)
    _add_shared_lib_path(env, job.path)

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(job.entry.resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(job.path.resolve()),
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f'Controller {job.entry.name} exceeded {timeout}s')

    return stdout_b.decode('utf-8', errors='replace'), stderr_b.decode('utf-8', errors='replace'), proc.returncode or 0


async def execute_job(
    job: Job,
    *,
    blotter_path: Path,
    memory_path: Path,
    email_to: list[str],
    config_path: Path | None = None,
    skip_email: bool = False,
    timeout: int = CONTROLLER_TIMEOUT_DEFAULT,
) -> tuple[str, str] | None:
    '''
    Execute a single job's controller and route its output.

    Returns (job_id, summary) on success, None on failure.
    Caller may set skip_email=True to batch emails across jobs.
    '''
    log = structlog.get_logger()
    log.info('executing job', job_id=job.id, entry=str(job.entry))

    extra_env: dict[str, str] = {}
    if config_path is not None:
        extra_env['ANYA_CONFIG_FILE'] = str(config_path.resolve())

    stdout, stderr, rc = await _run_controller(job, extra_env, timeout)

    if rc != 0:
        # User-facing summary: just the final exception line. Full stderr goes
        # to structlog so the terminal still has the traceback for debugging.
        summary_line = _final_error_line(stderr)
        log.error('controller failed', job_id=job.id, returncode=rc, stderr=stderr.strip()[:4000])
        raise RuntimeError(f'Controller for {job.id!r} exited {rc}: {summary_line}')

    summary, mem_content, resolved_content = _parse_blocks(stdout)

    if mem_content:
        append_memory(memory_path, job.id, mem_content)
    if resolved_content:
        prune_memory(memory_path, resolved_content)

    try:
        append_blotter(blotter_path, job.id, summary[:2000])
    except BlotterLockError as e:
        summary = f'**System issue**: {e}\n\n---\n\n{summary}'

    if email_to and not skip_email:
        html = f'<h2>Job: {job.id}</h2><pre>{summary}</pre>'
        await send_email(to=email_to, subject=f'[Anya] {job.id}', html=html, text=summary)

    log.info('job complete', job_id=job.id)
    return (job.id, summary)
