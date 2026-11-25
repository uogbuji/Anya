'''Shared helper for HTTP code that accepts an optional, caller-owned httpx client.'''

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx


@asynccontextmanager
async def client_or_new(
    client: httpx.AsyncClient | None,
    make: Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]],
) -> AsyncIterator[httpx.AsyncClient]:
    '''
    Use the caller's client as-is (its settings apply, and it stays open), or make one
    with `make()` for this call and close it afterwards. Passing a client is how tests
    inject `httpx.MockTransport`, and how a long-running caller reuses connections.
    '''
    if client is not None:
        yield client
    else:
        async with make() as new_client:
            yield new_client
