'''Data fetchers for jobs: HTTP, RSS, Reddit. Pluggable Web fetcher protocol.'''

from anya.fetchers.http import fetch_http
from anya.fetchers.protocol import (
    Crawl4AIFetcher,
    FetchResult,
    SimpleHttpFetcher,
    WebFetcher,
    create_fetcher,
    fetch_url,
)
from anya.fetchers.reddit import RedditFetcher
from anya.fetchers.rss import RSSFetcher, fetch_rss
from anya.fetchers.search import (
    BraveSearchFetcher,
    TavilySearchFetcher,
    WebSearcher,
    create_searcher,
    search_web,
)

__all__ = [
    'BraveSearchFetcher',
    'Crawl4AIFetcher',
    'FetchResult',
    'RedditFetcher',
    'RSSFetcher',
    'SimpleHttpFetcher',
    'TavilySearchFetcher',
    'WebFetcher',
    'WebSearcher',
    'create_fetcher',
    'create_searcher',
    'fetch_http',
    'fetch_rss',
    'fetch_url',
    'search_web',
]
