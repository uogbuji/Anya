'''Shared HTTP cache for fetchers (RFC 9111 via hishel).

A single SQLite-backed cache shared by all GET fetchers, so we send
`If-None-Match` / `If-Modified-Since` on revalidation and respect
`Cache-Control` / `Vary`. Be a good HTTP citizen.

Default path: `data/http-cache.sqlite` (set config.toml [paths] http_cache to override).
'''

from __future__ import annotations

from pathlib import Path

import hishel
import hishel.httpx as _hh

from anya.config import get_config


def _cache_db_path() -> Path:
    p = Path(get_config().paths.http_cache)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def cached_client(**kwargs) -> _hh.AsyncCacheClient:
    '''
    Return an httpx-compatible async client backed by the shared HTTP cache.

    Accepts the same kwargs as `httpx.AsyncClient` (timeout, follow_redirects,
    headers, verify, ...). Use as `async with cached_client(...) as client:`.
    '''
    storage = hishel.AsyncSqliteStorage(database_path=str(_cache_db_path()))
    return _hh.AsyncCacheClient(storage=storage, **kwargs)
