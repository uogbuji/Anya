'''APScheduler-based implementation. Install with: uv pip install anya[scheduler-apscheduler]'''

from collections.abc import Callable, Coroutine
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from anya.scheduler.base import Scheduler


class APSchedulerImpl(Scheduler):
    '''Uses APScheduler for cron-like scheduling.'''

    def __init__(self, interval_seconds: float = 86400) -> None:
        self._interval = interval_seconds
        self._scheduler = AsyncIOScheduler()
        self._callback: Callable[..., Coroutine[Any, Any, None]] | None = None
        self._args: tuple[Any, ...] = ()
        self._kwargs: dict[str, Any] = {}

    def schedule(
        self,
        callback: Callable[..., Coroutine[Any, Any, None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._callback = callback
        self._args = args
        self._kwargs = kwargs

    async def _job_wrapper(self) -> None:
        if self._callback:
            await self._callback(*self._args, **self._kwargs)

    async def start(self) -> None:
        if not self._callback:
            raise RuntimeError('No callback scheduled; call schedule() first')
        self._scheduler.add_job(
            self._job_wrapper,
            IntervalTrigger(seconds=self._interval),
            id='anya_main',
        )
        self._scheduler.start()

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
