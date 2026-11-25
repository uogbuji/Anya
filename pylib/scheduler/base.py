'''The scheduler seam. Implementations can use asyncio, cron, etc.'''

from collections.abc import Callable, Coroutine
from typing import Any, Protocol


class Scheduler(Protocol):
    '''Runs a callback on a schedule; implementations define the schedule. No base class needed.'''

    async def start(self) -> None:
        '''Start the scheduler.'''
        ...

    async def stop(self) -> None:
        '''Stop the scheduler.'''
        ...

    def schedule(
        self,
        callback: Callable[..., Coroutine[Any, Any, None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        '''Register a callback to run on the schedule.'''
        ...
