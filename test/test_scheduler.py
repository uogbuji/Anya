'''Unit tests for the asyncio loop scheduler.'''

import asyncio

from anya.scheduler.asyncio_loop import AsyncioLoopScheduler


def test_runs_immediately_repeats_and_stops_cleanly():
    async def scenario():
        calls = 0

        async def tick():
            nonlocal calls
            calls += 1

        sched = AsyncioLoopScheduler(interval_seconds=0.05)
        sched.schedule(tick)
        before = len(asyncio.all_tasks())
        await sched.start()
        await asyncio.sleep(0.18)
        await sched.stop()
        # Regression: each interval wait left a pending helper task behind.
        assert len(asyncio.all_tasks()) == before
        return calls

    assert asyncio.run(scenario()) >= 3


def test_stop_interrupts_a_long_interval():
    async def scenario():
        async def tick():
            pass

        sched = AsyncioLoopScheduler(interval_seconds=3600)
        sched.schedule(tick)
        await sched.start()
        await asyncio.sleep(0.01)
        await asyncio.wait_for(sched.stop(), timeout=1)

    asyncio.run(scenario())


def test_callback_errors_do_not_stop_the_loop():
    async def scenario():
        calls = 0

        async def flaky():
            nonlocal calls
            calls += 1
            raise RuntimeError('boom')

        sched = AsyncioLoopScheduler(interval_seconds=0.02)
        sched.schedule(flaky)
        await sched.start()
        await asyncio.sleep(0.1)
        await sched.stop()
        return calls

    assert asyncio.run(scenario()) >= 2
