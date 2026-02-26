'''
Job executor: fetch data, run Claude, update blotter/memory, send email.
Read-only; no destructive actions.
'''

import os
import subprocess
import sys
from pathlib import Path

from anthropic import AsyncAnthropic

from anya.actions import expand_actions
from anya.blotter import append_blotter, read_blotter
from anya.email_unosend import send_email
from anya.fetchers import fetch_url
from anya.fetchers.rss import fetch_rss
from anya.job.loader import Job, should_run_job
from anya.memory import append_memory, prune_memory, read_memory

SYSTEM_PROMPT = '''You are a read-only analysis agent. You NEVER take destructive actions.
You analyze data, summarize findings, and produce reports. You may instruct the system to:
- Append to the blotter (append-only log)
- Append to long-term memory (for critical findings only)
- Send an email report

You must NOT: delete, modify, overwrite, or perform any destructive operation.
Output your report in the requested format.'''

BLOB_PROMPT = '''
## Fetched data
{data}

## Recent blotter entries
{blotter}

## Long-term memory
{memory}

## Your task
Follow the instructions in MAIN.md. Produce a summary report.

**System Issues**: Only report issues that appear to be ongoing (evident in the most recent execution).
Do NOT report historical issues that have been resolved. If the current run succeeded, do not list
earlier failures (e.g. missing scripts, path errors) as current system issues.

If there are critical findings that should be remembered long-term, output a block:
---MEMORY---
<content to append to long-term memory>
---END MEMORY---

If previously stored memory is no longer accurate (e.g. an issue was resolved), output:
---RESOLVED---
<brief description of what was resolved, to prune from memory>
---END RESOLVED---

Otherwise, just produce the report. The report will be emailed and appended to the blotter.'''


async def run_job_py(job: Job) -> str:
    '''
    Run .py files in the job dir. Returns combined stdout. Uses job's .env.
    '''
    outputs: list[str] = []
    for py_file in sorted(job.path.glob('*.py')):
        if py_file.name.startswith('_'):
            continue
        env = os.environ.copy()
        env.update(job.env)
        env['ANYA_JOB_ID'] = job.id
        env['ANYA_JOB_PATH'] = str(job.path.resolve())
        if job.select is not None:
            env['ANYA_JOB_SELECT'] = str(job.select)
        result = subprocess.run(
            [sys.executable, str(py_file.resolve())],
            capture_output=True,
            text=True,
            cwd=str(job.path.resolve()),
            env=env,
            timeout=60,
        )
        if result.stdout:
            outputs.append(f'### {py_file.name}\n{result.stdout}')
        if result.stderr and result.returncode != 0:
            outputs.append(f'### {py_file.name} (stderr)\n{result.stderr}')
    return '\n\n'.join(outputs) if outputs else ''


async def execute_job(
    job: Job,
    *,
    blotter_path: Path,
    memory_path: Path,
    email_to: list[str],
    api_key: str | None = None,
) -> None:
    '''
    Execute a single job: fetch, Claude, blotter, memory, email.
    '''
    from tenacity import retry, stop_after_attempt, wait_exponential
    import structlog

    log = structlog.get_logger()
    log.info('executing job', job_id=job.id)

    # Set job env for this process (sandboxed from other jobs)
    for k, v in job.env.items():
        os.environ[k] = v

    # Gather context
    memory = read_memory(memory_path)
    blotter_lines = read_blotter(blotter_path, limit=50)
    blotter = '\n'.join(blotter_lines) if blotter_lines else '(empty)'

    # Run job .py scripts if any (read-only data gathering)
    py_output = await run_job_py(job)
    data_parts = [py_output] if py_output else []

    # MAIN.md can specify fetch/rss lines: "fetch: https://..." or "rss: https://..."
    for line in job.main_md.splitlines():
        raw = line.strip()
        low = raw.lower()
        if low.startswith('fetch:'):
            url = raw.split(':', 1)[1].strip()
            if url.startswith('http'):
                try:
                    result = await fetch_url(url)
                    data_parts.append(result.markdown if result.success else f'(fetch failed: {result.error})')
                except Exception as e:
                    data_parts.append(f'(fetch failed: {e})')
        elif low.startswith('rss:'):
            url = raw.split(':', 1)[1].strip()
            if url.startswith('http'):
                try:
                    data_parts.append(await fetch_rss(url))
                except Exception as e:
                    data_parts.append(f'(rss failed: {e})')

    data = '\n\n---\n\n'.join(data_parts) if data_parts else '(no fetched data)'

    # Expand ---ACTION---...---END ACTION--- blocks in MAIN.md
    main_md_expanded = await expand_actions(job.main_md)

    user_content = f'''# Job: {job.id}

## MAIN.md instructions
{main_md_expanded}
''' + BLOB_PROMPT.format(data=data, blotter=blotter, memory=memory)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_claude():
        client = AsyncAnthropic(api_key=api_key or os.environ.get('ANTHROPIC_API_KEY'))
        msg = await client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': user_content}],
        )
        return msg.content[0].text

    response = await _call_claude()

    # Parse memory block if present
    if '---MEMORY---' in response and '---END MEMORY---' in response:
        start = response.index('---MEMORY---') + len('---MEMORY---')
        end = response.index('---END MEMORY---')
        mem_content = response[start:end].strip()
        if mem_content:
            append_memory(memory_path, job.id, mem_content)

    # Parse RESOLVED block to prune stale memory
    if '---RESOLVED---' in response and '---END RESOLVED---' in response:
        start = response.index('---RESOLVED---') + len('---RESOLVED---')
        end = response.index('---END RESOLVED---')
        resolved_content = response[start:end].strip()
        if resolved_content:
            prune_memory(memory_path, resolved_content)

    # Blotter and email (exclude MEMORY and RESOLVED blocks from summary)
    summary = response.split('---MEMORY---')[0].split('---RESOLVED---')[0].strip()
    append_blotter(blotter_path, job.id, summary[:2000])  # truncate for blotter

    if email_to:
        html = f'<h2>Job: {job.id}</h2><pre>{summary}</pre>'
        await send_email(to=email_to, subject=f'[Anya] {job.id}', html=html, text=summary)

    log.info('job complete', job_id=job.id)
