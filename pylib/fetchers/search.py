'''
Web search ("SERP") fetchers: turn a *query* into a markdown list of result
URLs + snippets, so a controller can discover opportunities by search instead of
by crawling a fixed listing page.

Unlike the page fetchers (`fetch(url)`), a searcher takes a query
(`search(query)`) and returns a `FetchResult` whose markdown lists each result's
title, URL, and snippet. That markdown drops straight into the same
extract→validate pipeline the page fetchers feed: the result URLs appear
verbatim, so they serve as the allow-list for any URL the LLM later returns.

Providers:
  - **tavily** — Tavily Search API. Secret: `TAVILY_API_KEY` (env).
  - **brave**  — Brave Web Search API. Secret: `BRAVE_API_KEY` (env).

Non-secret knobs live in `config.toml [fetch]` (`tavily_max_results`,
`brave_max_results`). Keys are secrets and stay in the environment, like every
other Anya secret.
'''

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx
import structlog

from anya.config import get_config
from anya.fetchers.protocol import FetchResult


logger = structlog.get_logger()

TAVILY_SEARCH_URL = 'https://api.tavily.com/search'
BRAVE_SEARCH_URL = 'https://api.search.brave.com/res/v1/web/search'


def _results_to_markdown(query: str, results: list[dict]) -> str:
    '''
    Render normalized results ({title, url, snippet}) into markdown. Each URL is
    emitted verbatim on its own line so downstream URL allow-listing can find it.
    '''
    lines = [f'# Search results for: {query}', '']
    for r in results:
        title = (r.get('title') or '').strip() or '(untitled)'
        url = (r.get('url') or '').strip()
        snippet = (r.get('snippet') or '').strip()
        lines.append(f'## {title}')
        if url:
            lines.append(url)
        if snippet:
            lines.append('')
            lines.append(snippet)
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def _parse_tavily(data: dict) -> list[dict]:
    '''Normalize a Tavily /search JSON response to [{title, url, snippet}].'''
    out = []
    for r in (data.get('results') or []):
        if not isinstance(r, dict):
            continue
        out.append({
            'title': r.get('title', ''),
            'url': r.get('url', ''),
            'snippet': r.get('content', ''),
        })
    return out


def _parse_brave(data: dict) -> list[dict]:
    '''Normalize a Brave web-search JSON response to [{title, url, snippet}].'''
    out = []
    for r in ((data.get('web') or {}).get('results') or []):
        if not isinstance(r, dict):
            continue
        out.append({
            'title': r.get('title', ''),
            'url': r.get('url', ''),
            'snippet': r.get('description', ''),
        })
    return out


class WebSearcher(ABC):
    '''Protocol for query-based search providers (the SERP analogue of WebFetcher).'''

    @abstractmethod
    async def search(self, query: str) -> FetchResult:
        '''Run a search and return its results rendered as markdown.'''
        ...


class TavilySearchFetcher(WebSearcher):
    '''Tavily Search API. Key from `TAVILY_API_KEY`; result count from config.'''

    def __init__(self, api_key: str | None = None, max_results: int | None = None,
                 timeout: float = 30.0):
        self.api_key = api_key or os.environ.get('TAVILY_API_KEY')
        self.max_results = max_results if max_results is not None else get_config().fetch.tavily_max_results
        self.timeout = timeout

    async def search(self, query: str) -> FetchResult:
        if not self.api_key:
            logger.warning('TAVILY_API_KEY not set; tavily search skipped', query=query)
            return FetchResult(url=query, markdown='', success=False, error='TAVILY_API_KEY not set')
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(TAVILY_SEARCH_URL, json={
                    'api_key': self.api_key,
                    'query': query,
                    'max_results': self.max_results,
                    'search_depth': 'basic',
                })
                resp.raise_for_status()
                results = _parse_tavily(resp.json())
        except Exception as e:  # noqa: BLE001
            return FetchResult(url=query, markdown='', success=False, error=f'Tavily search failed: {e}')
        return FetchResult(url=query, markdown=_results_to_markdown(query, results),
                           title=f'Tavily: {query}', success=True)


class BraveSearchFetcher(WebSearcher):
    '''Brave Web Search API. Key from `BRAVE_API_KEY`; result count from config.'''

    def __init__(self, api_key: str | None = None, max_results: int | None = None,
                 timeout: float = 30.0):
        self.api_key = api_key or os.environ.get('BRAVE_API_KEY')
        self.max_results = max_results if max_results is not None else get_config().fetch.brave_max_results
        self.timeout = timeout

    async def search(self, query: str) -> FetchResult:
        if not self.api_key:
            logger.warning('BRAVE_API_KEY not set; brave search skipped', query=query)
            return FetchResult(url=query, markdown='', success=False, error='BRAVE_API_KEY not set')
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(BRAVE_SEARCH_URL, params={
                    'q': query,
                    'count': self.max_results,
                }, headers={
                    'X-Subscription-Token': self.api_key,
                    'Accept': 'application/json',
                })
                resp.raise_for_status()
                results = _parse_brave(resp.json())
        except Exception as e:  # noqa: BLE001
            return FetchResult(url=query, markdown='', success=False, error=f'Brave search failed: {e}')
        return FetchResult(url=query, markdown=_results_to_markdown(query, results),
                           title=f'Brave: {query}', success=True)


def create_searcher(provider: str = 'tavily', **kwargs) -> WebSearcher:
    '''
    Factory for a search provider. `provider` is 'tavily' or 'brave'. Mirrors
    create_fetcher, but searchers take a query rather than a URL.
    '''
    if provider == 'tavily':
        return TavilySearchFetcher(**kwargs)
    if provider == 'brave':
        return BraveSearchFetcher(**kwargs)
    raise ValueError(f'Unknown search provider: {provider}')


async def search_web(query: str, *, provider: str = 'tavily',
                     searcher: WebSearcher | None = None) -> FetchResult:
    '''Run a search and return markdown results. Convenience for jobs/controllers.'''
    s = searcher or create_searcher(provider)
    return await s.search(query)
