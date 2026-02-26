'''
Web fetcher protocol for retrieving and converting web content to markdown.

Provides a pluggable interface for different web scraping tools.
Adapted from WebScout pattern for use in Anya jobs.
'''

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import structlog

from ogbujipt.text.html import clean_html, html2markdown


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
        pass


class SimpleHttpFetcher(WebFetcher):
    '''
    Simple HTTP fetcher using httpx and OgbujiPT HTML processing.

    Best for: Static HTML pages without heavy JavaScript.
    '''

    def __init__(self, timeout: float = 30.0, follow_redirects: bool = True):
        self.timeout = timeout
        self.follow_redirects = follow_redirects

    async def fetch(self, url: str) -> FetchResult:
        '''Fetch URL with httpx and convert HTML to markdown.'''
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=self.follow_redirects,
                verify=False,  # Some sites have SSL issues
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                html = response.content.decode(response.encoding or 'utf-8')
                tree, _ = clean_html(html)
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

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get('CRAWL4AI_BASE_URL', 'http://localhost:11235')).rstrip('/')

    async def fetch(self, url: str) -> FetchResult:
        '''Fetch URL using Crawl4AI service.'''
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
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
        fetcher_type: 'simple' (plain HTTP) or 'crawl4ai' (Crawl4AI service)
        **kwargs: Additional arguments for the fetcher

    Returns:
        WebFetcher instance
    '''
    if fetcher_type in ('simple', 'plain'):
        return SimpleHttpFetcher(**kwargs)
    if fetcher_type == 'crawl4ai':
        return Crawl4AIFetcher(**kwargs)
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
