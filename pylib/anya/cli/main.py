'''CLI for headless Claude agent runner.'''

import asyncio
from pathlib import Path

import fire
import structlog
from rich.console import Console
from rich.panel import Panel

from anya.runner import run_tick
from anya.scheduler import get_scheduler


def _configure_plain_tracebacks() -> None:
    '''Use standard Python tracebacks instead of Rich's fancy format.'''
    from structlog.contextvars import merge_contextvars
    from structlog.dev import ConsoleRenderer, plain_traceback, set_exc_info
    from structlog.processors import StackInfoRenderer, TimeStamper, add_log_level

    structlog.configure(
        processors=[
            merge_contextvars,
            add_log_level,
            StackInfoRenderer(),
            set_exc_info,
            TimeStamper(fmt='%Y-%m-%d %H:%M:%S', utc=False),
            ConsoleRenderer(exception_formatter=plain_traceback),
        ],
    )


def main() -> None:
    '''Anya: headless Claude agent runner.'''
    _configure_plain_tracebacks()
    fire.Fire({
        'run': run_once,
        'serve': serve,
    })


def run_once(
    job_dir: str = 'job',
    blotter: str = 'data/blotter.txt',
    memory: str = 'data/memory.txt',
    email_to: str = '',
    phases: str = 'default',
) -> None:
    '''
    Run one tick: discover jobs, run due ones, email report.
    job_dir: directory containing job subdirs (each with MAIN.md)
    blotter: path to append-only log
    memory: path to long-term memory
    email_to: comma-separated email addresses for reports
    phases: comma-separated phases to include (default: default). Jobs with phase: ignore
      are skipped unless "ignore" is in phases.
    '''
    job_path = Path(job_dir)
    blotter_path = Path(blotter)
    memory_path = Path(memory)
    to_list = [e.strip() for e in email_to.split(',') if e.strip()]
    phase_set = {p.strip() for p in phases.split(',') if p.strip()}
    asyncio.run(run_tick(job_path, blotter_path, memory_path, to_list, phases=phase_set))


def serve(
    job_dir: str = 'job',
    blotter: str = 'data/blotter.txt',
    memory: str = 'data/memory.txt',
    email_to: str = '',
    interval: float = 86400,
    scheduler: str = 'asyncio',
    phases: str = 'default',
) -> None:
    '''
    Run scheduler: tick every interval seconds (default 24h).
    phases: comma-separated phases to include (default: default).
    '''
    console = Console()
    job_path = Path(job_dir)
    blotter_path = Path(blotter)
    memory_path = Path(memory)
    to_list = [e.strip() for e in email_to.split(',') if e.strip()]
    phase_set = {p.strip() for p in phases.split(',') if p.strip()}

    async def tick():
        await run_tick(job_path, blotter_path, memory_path, to_list, phases=phase_set)

    sched = get_scheduler(kind=scheduler, interval_seconds=interval)
    sched.schedule(tick)

    console.print(Panel(f'Starting Anya scheduler (interval={interval}s)', title='Anya'))
    asyncio.run(_serve(sched))


async def _serve(scheduler) -> None:
    await scheduler.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await scheduler.stop()
