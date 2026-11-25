'''Simple asyncio-based recurring scheduler.'''

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

import structlog


class AsyncioLoopScheduler:
    '''Runs a callback, then waits interval_seconds (or until stopped), repeatedly.'''

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
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._callback(*self._args, **self._kwargs)
            except Exception:
                # Log but don't crash the loop
                structlog.get_logger().exception('scheduler callback failed')
            # Wait out the interval, waking early if stop() is called. (No helper tasks:
            # the old asyncio.wait over two new tasks left one pending every tick.)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self._interval):
                    await self._stop_event.wait()
