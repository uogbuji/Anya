'''Scheduler implementations. Swap via the scheduler= param (`anya serve --scheduler=...`).'''

from collections.abc import Callable

from anya.scheduler.asyncio_loop import AsyncioLoopScheduler
from anya.scheduler.base import Scheduler

__all__ = ['Scheduler', 'AsyncioLoopScheduler', 'SCHEDULERS', 'get_scheduler']

# Scheduler name → constructor taking interval_seconds. Add entries to plug in others.
SCHEDULERS: dict[str, Callable[..., Scheduler]] = {'asyncio': AsyncioLoopScheduler}


def get_scheduler(kind: str = 'asyncio', interval_seconds: float = 86400) -> Scheduler:
    '''Create a scheduler by name (see SCHEDULERS).'''
    try:
        factory = SCHEDULERS[kind]
    except KeyError:
        raise ValueError(f'unknown scheduler {kind!r}. Available: {sorted(SCHEDULERS)}') from None
    return factory(interval_seconds=interval_seconds)
