'''CLI for the Anya headless agent runner.'''

import asyncio
import os
from pathlib import Path

import fire
import structlog
from rich.console import Console
from rich.panel import Panel

from anya.config import AnyaConfig, get_config
from anya.job.loader import discover_jobs
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


def _parse_csv_set(value: str) -> set[str] | None:
    '''Parse comma-separated tokens into a set, or None when empty.'''
    items = {e.strip() for e in value.split(',') if e.strip()}
    return items or None


def _resolve_email_to(email_to: str, cfg: AnyaConfig) -> list[str]:
    '''Report recipients: --email_to (comma-separated) when given, else config.toml [email] to.'''
    if email_to:
        return [e.strip() for e in email_to.split(',') if e.strip()]
    return list(cfg.email.to)


def _resolve_config_path(config: str) -> Path | None:
    '''Resolve the config path argument. Empty string → search default locations.'''
    if config:
        return Path(config)
    candidate = Path('config.toml')
    if candidate.exists():
        return candidate
    env = os.environ.get('ANYA_CONFIG_FILE')
    if env:
        return Path(env)
    return None


def main() -> None:
    '''Anya: headless LLM agent runner.'''
    _configure_plain_tracebacks()
    fire.Fire({
        'run': run_once,
        'serve': serve,
    })


def run_once(
    job_dir: str = 'job',
    blotter: str = '',
    memory: str = '',
    email_to: str = '',
    phases: str = 'default',
    select_jobs: str = '',
    exclude_jobs: str = '',
    config: str = '',
) -> None:
    '''
    Run one tick: discover jobs, run due ones, email report.

    job_dir: directory containing job subdirs (each with anya.toml)
    blotter: path to append-only log (default: config.toml [paths] blotter)
    memory: path to long-term memory (default: config.toml [paths] memory)
    email_to: comma-separated email addresses for reports (default: config.toml [email] to)
    phases: comma-separated phases to include (default: default). Jobs with phase: ignore
      are skipped unless "ignore" is in phases.
    select_jobs: comma-separated job ids to run (bypasses frequency; for dev/testing)
    exclude_jobs: comma-separated job ids to skip (after phase and select filters)
    config: path to Anya config.toml (default: ./config.toml if present, else ANYA_CONFIG_FILE env)
    '''
    job_path = Path(job_dir)

    # A one-shot run with no jobs is almost always a misconfigured/absent job dir (e.g. a
    # botched bind mount). Warn rather than refuse — unlike `serve`, a single tick that does
    # nothing is harmless, and dev may legitimately point at a sparse dir.
    if not discover_jobs(job_path):
        structlog.get_logger().warning(
            'no jobs found; nothing to run', job_dir=str(job_path))

    config_path = _resolve_config_path(config)
    cfg = get_config(config_path, reload=True)
    blotter_path = Path(blotter or cfg.paths.blotter)
    memory_path = Path(memory or cfg.paths.memory)
    to_list = _resolve_email_to(email_to, cfg)
    phase_set = {p.strip() for p in phases.split(',') if p.strip()}
    asyncio.run(
        run_tick(
            job_path,
            blotter_path,
            memory_path,
            to_list,
            phases=phase_set,
            config_path=config_path,
            select_jobs=_parse_csv_set(select_jobs),
            exclude_jobs=_parse_csv_set(exclude_jobs),
        )
    )


def serve(
    job_dir: str = 'job',
    blotter: str = '',
    memory: str = '',
    email_to: str = '',
    interval: float = 86400,
    scheduler: str = 'asyncio',
    phases: str = 'default',
    select_jobs: str = '',
    exclude_jobs: str = '',
    config: str = '',
) -> None:
    '''
    Run scheduler: tick every interval seconds (default 24h).

    Paths and recipients default to config.toml ([paths]/[email]); CLI flags override.
    '''
    console = Console()
    job_path = Path(job_dir)

    # Fail loud on a missing/empty job dir rather than ticking forever doing nothing.
    # Under containerized deploy the job dir is a bind mount; a botched or absent mount
    # surfaces here at startup instead of silently running zero jobs (see doc/DEPLOYMENT.md).
    discovered = discover_jobs(job_path)
    if not discovered:
        console.print(Panel(
            f'No jobs found under [bold]{job_path}/[/bold] — refusing to start.\n'
            'Each job is a subdirectory containing an anya.toml. If deploying, check that '
            'the job directory is mounted and populated (ANYA_JOB_DIR / compose volume).',
            title='Anya: no jobs', border_style='red'))
        raise SystemExit(2)

    config_path = _resolve_config_path(config)
    cfg = get_config(config_path, reload=True)
    blotter_path = Path(blotter or cfg.paths.blotter)
    memory_path = Path(memory or cfg.paths.memory)
    to_list = _resolve_email_to(email_to, cfg)
    phase_set = {p.strip() for p in phases.split(',') if p.strip()}
    select_set = _parse_csv_set(select_jobs)
    exclude_set = _parse_csv_set(exclude_jobs)

    async def tick():
        await run_tick(
            job_path,
            blotter_path,
            memory_path,
            to_list,
            phases=phase_set,
            config_path=config_path,
            select_jobs=select_set,
            exclude_jobs=exclude_set,
        )

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
