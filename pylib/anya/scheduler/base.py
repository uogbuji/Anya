'''Modular scheduler abstraction. Implementations can use asyncio, APScheduler, cron, etc.'''

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any


class Scheduler(ABC):
    '''Abstract scheduler. Run a callback on a schedule; implementations define the schedule.'''

    @abstractmethod
    async def start(self) -> None:
        '''Start the scheduler.'''

    @abstractmethod
    async def stop(self) -> None:
        '''Stop the scheduler.'''

    @abstractmethod
    def schedule(
        self,
        callback: Callable[..., Coroutine[Any, Any, None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        '''Register a callback to run on the schedule.'''
