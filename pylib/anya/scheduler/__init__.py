'''Scheduler implementations. Swap via scheduler= param or env.'''

from anya.scheduler.base import Scheduler
from anya.scheduler.asyncio_loop import AsyncioLoopScheduler

__all__ = ['Scheduler', 'AsyncioLoopScheduler']


def get_scheduler(kind: str = 'asyncio', interval_seconds: float = 86400) -> Scheduler:
    '''
    Factory for scheduler. kind: asyncio (default), apscheduler (if installed).
    '''
    if kind == 'asyncio':
        return AsyncioLoopScheduler(interval_seconds=interval_seconds)
    if kind == 'apscheduler':
        from anya.scheduler.apscheduler_impl import APSchedulerImpl
        return APSchedulerImpl(interval_seconds=interval_seconds)
    raise ValueError(f'unknown scheduler: {kind}')
