'''Simple asyncio-based recurring scheduler.'''

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from anya.scheduler.base import Scheduler


class AsyncioLoopScheduler(Scheduler):
    '''Runs a callback on a fixed interval using asyncio.sleep.'''

    def __init__(self, interval_seconds: float = 86400) -> None:
        '''
        interval_seconds: how often to run (default 24h). Main schedule granularity.
        '''
        self._interval = interval_seconds
        self._callback: Callable[..., Coroutine[Any, Any, None]] | None = None
        self._args: tuple[Any, ...] = ()
        self._kwargs: dict[str, Any] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def schedule(
        self,
        callback: Callable[..., Coroutine[Any, Any, None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._callback = callback
        self._args = args
        self._kwargs = kwargs

    async def start(self) -> None:
        if not self._callback:
            raise RuntimeError('No callback scheduled; call schedule() first')
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._callback(*self._args, **self._kwargs)
            except Exception:
                # Log but don't crash the loop
                import structlog
                structlog.get_logger().exception('scheduler callback failed')
            await asyncio.wait(
                [asyncio.create_task(self._stop_event.wait()), asyncio.create_task(asyncio.sleep(self._interval))],
                return_when=asyncio.FIRST_COMPLETED,
            )
