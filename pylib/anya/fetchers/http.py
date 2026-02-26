'''HTTP fetcher using httpx.'''

import httpx


async def fetch_http(url: str, headers: dict[str, str] | None = None) -> str:
    '''
    Fetch URL and return body as text. Read-only; no destructive actions.
    '''
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.text
