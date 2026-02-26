'''CLI for headless LLM agent runner (Anthropic Claude, OpenAI-compatible).'''

import asyncio
from pathlib import Path

import fire
import structlog
from rich.console import Console
from rich.panel import Panel

from anya.llm import LLMConfig
from anya.runner import run_tick
from anya.scheduler import get_scheduler


def _build_llm_config(provider: str = '', model: str = '', llm_base_url: str = '') -> LLMConfig:
    '''Build LLMConfig from env, with optional CLI overrides.'''
    cfg = LLMConfig.from_env(provider=provider or None, model=model or None)
    if llm_base_url:
        cfg = LLMConfig(provider=cfg.provider, model=cfg.model, api_key=cfg.api_key, base_url=llm_base_url)
    return cfg


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
    '''Anya: headless LLM agent runner (Claude, OpenAI-compatible).'''
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
    provider: str = '',
    model: str = '',
    llm_base_url: str = '',
) -> None:
    '''
    Run one tick: discover jobs, run due ones, email report.
    job_dir: directory containing job subdirs (each with MAIN.md)
    blotter: path to append-only log
    memory: path to long-term memory
    email_to: comma-separated email addresses for reports
    phases: comma-separated phases to include (default: default). Jobs with phase: ignore
      are skipped unless "ignore" is in phases.
    provider: llm provider (anthropic | openai). Default from LLM_PROVIDER env.
    model: model name. Default from LLM_MODEL env.
    llm_base_url: base URL for OpenAI-compatible API (e.g. http://localhost:8080/v1).
    '''
    job_path = Path(job_dir)
    blotter_path = Path(blotter)
    memory_path = Path(memory)
    to_list = [e.strip() for e in email_to.split(',') if e.strip()]
    phase_set = {p.strip() for p in phases.split(',') if p.strip()}
    llm_config = _build_llm_config(provider, model, llm_base_url)
    asyncio.run(run_tick(job_path, blotter_path, memory_path, to_list, phases=phase_set, llm_config=llm_config))


def serve(
    job_dir: str = 'job',
    blotter: str = 'data/blotter.txt',
    memory: str = 'data/memory.txt',
    email_to: str = '',
    interval: float = 86400,
    scheduler: str = 'asyncio',
    phases: str = 'default',
    provider: str = '',
    model: str = '',
    llm_base_url: str = '',
) -> None:
    '''
    Run scheduler: tick every interval seconds (default 24h).
    phases: comma-separated phases to include (default: default).
    provider, model, llm_base_url: LLM config (see run).
    '''
    console = Console()
    job_path = Path(job_dir)
    blotter_path = Path(blotter)
    memory_path = Path(memory)
    to_list = [e.strip() for e in email_to.split(',') if e.strip()]
    phase_set = {p.strip() for p in phases.split(',') if p.strip()}
    llm_config = _build_llm_config(provider, model, llm_base_url)

    async def tick():
        await run_tick(job_path, blotter_path, memory_path, to_list, phases=phase_set, llm_config=llm_config)

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
