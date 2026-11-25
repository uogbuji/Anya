'''Scheduler implementations. Swap via the scheduler= param (`anya serve --scheduler=...`).'''

from anya.scheduler.base import Scheduler
from anya.scheduler.asyncio_loop import AsyncioLoopScheduler

__all__ = ['Scheduler', 'AsyncioLoopScheduler']


def get_scheduler(kind: str = 'asyncio', interval_seconds: float = 86400) -> Scheduler:
    '''Factory for scheduler. kind: asyncio (the only built-in today).'''
    if kind == 'asyncio':
        return AsyncioLoopScheduler(interval_seconds=interval_seconds)
    raise ValueError(f'unknown scheduler: {kind}')
