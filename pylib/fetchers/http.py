'''HTTP fetcher using httpx.'''

import httpx

from anya._http import client_or_new


async def fetch_http(url: str, headers: dict[str, str] | None = None, *,
                     client: httpx.AsyncClient | None = None) -> str:
    '''
    Fetch URL and return body as text. Read-only; no destructive actions.
    '''
    async with client_or_new(client, lambda: httpx.AsyncClient(timeout=30.0)) as c:
        resp = await c.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.text
