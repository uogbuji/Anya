'''Data fetchers for jobs: HTTP, RSS. Pluggable Web fetcher protocol.'''

from anya.fetchers.http import fetch_http
from anya.fetchers.protocol import (
    Crawl4AIFetcher,
    FetchResult,
    SimpleHttpFetcher,
    WebFetcher,
    create_fetcher,
    fetch_url,
)
from anya.fetchers.rss import fetch_rss

__all__ = [
    'Crawl4AIFetcher',
    'FetchResult',
    'SimpleHttpFetcher',
    'WebFetcher',
    'create_fetcher',
    'fetch_http',
    'fetch_rss',
    'fetch_url',
]
