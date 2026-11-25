'''
Web fetcher protocol for retrieving and converting web content to markdown.

Provides a pluggable interface for different web scraping tools.
Adapted from WebScout pattern for use in Anya jobs.
'''

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from anya._http import client_or_new
from anya.config import get_config
from anya.fetchers._cache import cached_client
from anya.fetchers._html import clean_html, html2markdown


logger = structlog.get_logger()


@dataclass
class FetchResult:
    '''Result of fetching a web page.'''

    url: str
    markdown: str
    title: str | None = None
    success: bool = True
    error: str | None = None


class WebFetcher(Protocol):
    '''Anything with an async fetch(url) -> FetchResult. No base class needed.'''

    async def fetch(self, url: str) -> FetchResult:
        '''Fetch a URL and return its content as markdown.'''
        ...


# Fetch method name → constructor. Each fetcher module registers its own entries; the
# anya.fetchers package imports them all, so the registry is full before any lookup.
FETCHERS: dict[str, Callable[..., WebFetcher]] = {}


def register_fetcher(name: str, factory: Callable[..., WebFetcher]) -> None:
    '''Make a fetch method available to create_fetcher() (and `anya fetch --method`).'''
    FETCHERS[name] = factory


class SimpleHttpFetcher:
    '''
    Simple HTTP fetcher using httpx and OgbujiPT HTML processing.

    Best for: Static HTML pages without heavy JavaScript.

    drop_tabindex_minus_one: also strip tabindex="-1" elements during cleaning
    (see anya.fetchers._html.clean_html). Off by default.
    verify: check TLS certificates (default). Set False only for a specific site you
      trust whose certificate is broken; it lets anyone on the path alter the content.
    client: an httpx.AsyncClient to use instead of the shared cached one (its own
      timeout/redirect/TLS settings then apply).
    '''

    def __init__(self, timeout: float = 30.0, follow_redirects: bool = True,
                 drop_tabindex_minus_one: bool = False, verify: bool = True,
                 client: httpx.AsyncClient | None = None):
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.drop_tabindex_minus_one = drop_tabindex_minus_one
        self.verify = verify
        self.client = client

    async def fetch(self, url: str) -> FetchResult:
        '''Fetch URL with httpx and convert HTML to markdown.'''
        try:
            async with client_or_new(self.client, lambda: cached_client(
                timeout=self.timeout,
                follow_redirects=self.follow_redirects,
                verify=self.verify,
            )) as client:
                response = await client.get(url)
                response.raise_for_status()

                html = response.content.decode(response.encoding or 'utf-8')
                tree, _ = clean_html(html, drop_tabindex_minus_one=self.drop_tabindex_minus_one)
                markdown = html2markdown(tree)

                title = None
                title_elem = tree.css_first('title')
                if title_elem:
                    title = title_elem.text(strip=True)

                return FetchResult(
                    url=url,
                    markdown=markdown,
                    title=title,
                    success=True,
                )

        except Exception as e:
            return FetchResult(
                url=url,
                markdown='',
                success=False,
                error=str(e),
            )


class Crawl4AIFetcher:
    '''
    Fetcher using Crawl4AI for JavaScript-heavy or bot-blocked sites.

    Requires: Crawl4AI service running (via docker or local install)
    Best for: Dynamic sites, sites that block simple HTTP (e.g. Reddit)

    Run: docker run -p 11235:11235 unclecode/crawl4ai:basic
    '''

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None):
        self.base_url = (base_url or get_config().fetch.crawl4ai_base_url).rstrip('/')
        self.client = client

    async def fetch(self, url: str) -> FetchResult:
        '''Fetch URL using Crawl4AI service.'''
        try:
            async with client_or_new(self.client, lambda: httpx.AsyncClient(timeout=60.0)) as client:
                response = await client.post(
                    f'{self.base_url}/crawl',
                    json={
                        'urls': [url],
                        'word_count_threshold': 10,
                        'only_text': False,
                        'bypass_cache': False,
                    },
                )
                response.raise_for_status()
                result = response.json()

                if result.get('success') and result.get('results'):
                    page_result = result['results'][0]
                    markdown_data = page_result.get('markdown', '')

                    if isinstance(markdown_data, dict):
                        markdown = (
                            markdown_data.get('raw_markdown')
                            or markdown_data.get('markdown')
                            or markdown_data.get('content')
                            or markdown_data.get('text')
                            or ''
                        )
                    elif isinstance(markdown_data, str):
                        markdown = markdown_data
                    else:
                        markdown = str(markdown_data) if markdown_data else ''

                    title = page_result.get('title')
                    return FetchResult(
                        url=url,
                        markdown=markdown,
                        title=title,
                        success=True,
                    )
                else:
                    error = result.get('error', 'Unknown error')
                    return FetchResult(
                        url=url,
                        markdown='',
                        success=False,
                        error=error,
                    )

        except Exception as e:
            return FetchResult(
                url=url,
                markdown='',
                success=False,
                error=f'Crawl4AI fetch failed: {str(e)}',
            )


def create_fetcher(fetcher_type: str = 'plain', **kwargs) -> WebFetcher:
    '''
    Create a fetcher by method name: 'plain' (alias 'simple'), 'crawl4ai', 'reddit', 'rss',
    or any name added with register_fetcher(). kwargs go to the fetcher's constructor.
    '''
    try:
        factory = FETCHERS[fetcher_type]
    except KeyError:
        raise ValueError(f'Unknown fetcher type {fetcher_type!r}. Registered: {sorted(FETCHERS)}') from None
    return factory(**kwargs)


async def fetch_url(
    url: str,
    fetcher: WebFetcher | None = None,
) -> FetchResult:
    '''
    Fetch a URL and return markdown. Convenience for jobs and actions.

    Args:
        url: URL to fetch
        fetcher: Optional fetcher instance; defaults to SimpleHttpFetcher

    Returns:
        FetchResult with markdown content
    '''
    f = fetcher or create_fetcher('plain')
    return await f.fetch(url)


register_fetcher('plain', SimpleHttpFetcher)
register_fetcher('simple', SimpleHttpFetcher)
register_fetcher('crawl4ai', Crawl4AIFetcher)
