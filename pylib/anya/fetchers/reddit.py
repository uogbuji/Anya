'''
Reddit fetcher: hits old.reddit.com with a real User-Agent, falls back to the
URL's RSS feed when blocked.

Avoids modern reddit.com (heavy JS / aggressive bot blocking) without
requiring crawl4ai or Playwright. Set REDDIT_USER_AGENT in env to override
the default UA — Reddit's API rules say the UA should identify the bot.
'''

from __future__ import annotations

import os
import re
from urllib.parse import urlparse, urlunparse

from ogbujipt.text.html import clean_html, html2markdown

from anya.fetchers._cache import cached_client
from anya.fetchers.protocol import FetchResult, WebFetcher
from anya.fetchers.rss import fetch_rss


DEFAULT_USER_AGENT = 'python:anya:0.2 (by /u/anya)'

_REDDIT_HOST_RE = re.compile(r'^(https?://)(?:[a-z0-9.-]+\.)?reddit\.com', re.IGNORECASE)


def _to_old_reddit(url: str) -> str:
    '''Rewrite any reddit.com URL to old.reddit.com.'''
    return _REDDIT_HOST_RE.sub(r'\1old.reddit.com', url)


def _to_rss(url: str) -> str:
    '''
    Append `.rss` to a reddit URL's path. Subreddit pages, comment threads,
    user pages, and search results all support `.rss`.
    '''
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    if not path.endswith('.rss'):
        path = f'{path}.rss'
    return urlunparse(parsed._replace(netloc='old.reddit.com', path=path))


class RedditFetcher(WebFetcher):
    '''Reddit-aware fetcher: old.reddit.com with UA → RSS fallback.'''

    def __init__(self, user_agent: str | None = None, timeout: float = 30.0):
        self.user_agent = user_agent or os.environ.get('REDDIT_USER_AGENT', DEFAULT_USER_AGENT)
        self.timeout = timeout

    async def fetch(self, url: str) -> FetchResult:
        old_url = _to_old_reddit(url)
        fallback_reason: str
        try:
            async with cached_client(
                timeout=self.timeout,
                follow_redirects=True,
                headers={'User-Agent': self.user_agent},
            ) as client:
                resp = await client.get(old_url)
            if 200 <= resp.status_code < 300:
                html = resp.content.decode(resp.encoding or 'utf-8', errors='replace')
                tree, _ = clean_html(html)
                title_elem = tree.css_first('title')
                return FetchResult(
                    url=old_url,
                    markdown=html2markdown(tree),
                    title=title_elem.text(strip=True) if title_elem else None,
                    success=True,
                )
            fallback_reason = f'old.reddit.com returned HTTP {resp.status_code}'
        except Exception as e:  # noqa: BLE001
            fallback_reason = f'old.reddit.com fetch failed: {e}'

        # RSS fallback.
        rss_url = _to_rss(url)
        try:
            markdown = await fetch_rss(rss_url)
        except Exception as e:  # noqa: BLE001
            return FetchResult(
                url=url,
                markdown='',
                success=False,
                error=f'{fallback_reason}; RSS fallback ({rss_url}) failed: {e}',
            )
        return FetchResult(url=rss_url, markdown=markdown, title=None, success=True)
