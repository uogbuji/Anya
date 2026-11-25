'''Shared HTTP cache for fetchers (RFC 9111 via hishel).

A single SQLite-backed cache shared by all GET fetchers, so we send
`If-None-Match` / `If-Modified-Since` on revalidation and respect
`Cache-Control` / `Vary`. Be a good HTTP citizen.

Default path: `data/http-cache.sqlite` (set config.toml [paths] http_cache to override).
'''

import sqlite3
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import hishel
import hishel.httpx as _hh
import structlog

from anya.config import get_config


# Columns of the `entries` table in a hishel 1.x cache. hishel 2 refuses such a
# database at the first request ("This database is a Hishel 1.x cache"), which
# would fail every fetch until someone deleted the file by hand.
_HISHEL1_ENTRY_COLUMNS = frozenset({'id', 'cache_key', 'data', 'created_at', 'deleted_at'})


def _retire_hishel1_cache(path: Path) -> None:
    '''
    If `path` is a hishel 1.x cache, move it (and its WAL/SHM sidecars) aside so
    hishel 2 starts a fresh one. It's only a cache, so nothing is lost but warm entries.
    '''
    if not path.is_file():
        return
    try:
        with sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True) as conn:
            columns = {row[1] for row in conn.execute('PRAGMA table_info(entries)')}
    except sqlite3.DatabaseError:
        return  # not something we recognize; leave it for hishel to report
    if columns != _HISHEL1_ENTRY_COLUMNS:
        return
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    for sidecar in ('', '-wal', '-shm'):
        old = path.with_name(path.name + sidecar)
        if old.exists():
            old.rename(old.with_name(f'{old.name}.hishel1-{stamp}'))
    structlog.get_logger().warning('moved aside an old hishel 1.x HTTP cache; starting a fresh one',
                                   path=str(path), renamed_suffix=f'.hishel1-{stamp}')


@cache
def _prepare(path: Path) -> None:
    '''Create the cache dir and retire a hishel 1.x database — once per path per process.'''
    path.parent.mkdir(parents=True, exist_ok=True)
    _retire_hishel1_cache(path)


def _cache_db_path() -> Path:
    p = Path(get_config().paths.http_cache)
    _prepare(p)
    return p


def cached_client(**kwargs) -> _hh.AsyncCacheClient:
    '''
    Return an httpx-compatible async client backed by the shared HTTP cache.

    Accepts the same kwargs as `httpx.AsyncClient` (timeout, follow_redirects,
    headers, verify, ...). Use as `async with cached_client(...) as client:`.
    '''
    storage = hishel.AsyncSqliteStorage(database_path=str(_cache_db_path()))
    return _hh.AsyncCacheClient(storage=storage, **kwargs)
