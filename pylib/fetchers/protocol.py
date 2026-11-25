'''
Web fetcher protocol for retrieving and converting web content to markdown.

Provides a pluggable interface for different web scraping tools.
Adapted from WebScout pattern for use in Anya jobs.
'''

from abc import ABC, abstractmethod
from dataclasses import dataclass

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


class WebFetcher(ABC):
    '''Protocol for web content fetchers.'''

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult:
        '''
        Fetch a URL and return markdown content.

        Args:
            url: URL to fetch

        Returns:
            FetchResult with markdown content
        '''


class SimpleHttpFetcher(WebFetcher):
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


class Crawl4AIFetcher(WebFetcher):
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


def create_fetcher(fetcher_type: str = 'simple', **kwargs) -> WebFetcher:
    '''
    Factory function to create a web fetcher.

    Args:
        fetcher_type: 'simple' / 'plain', 'crawl4ai', or 'reddit'
        **kwargs: Additional arguments for the fetcher

    Returns:
        WebFetcher instance
    '''
    if fetcher_type in ('simple', 'plain'):
        return SimpleHttpFetcher(**kwargs)
    if fetcher_type == 'crawl4ai':
        return Crawl4AIFetcher(**kwargs)
    if fetcher_type == 'reddit':
        from anya.fetchers.reddit import RedditFetcher  # local import to avoid cycle
        return RedditFetcher(**kwargs)
    if fetcher_type == 'rss':
        from anya.fetchers.rss import RSSFetcher  # local import to avoid cycle
        return RSSFetcher(**kwargs)
    raise ValueError(f'Unknown fetcher type: {fetcher_type}')


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
    f = fetcher or create_fetcher('simple')
    return await f.fetch(url)
