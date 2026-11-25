'''
Reddit fetcher: hits old.reddit.com with a real User-Agent, falls back to the
URL's RSS feed when blocked.

Avoids modern reddit.com (heavy JS / aggressive bot blocking) without
requiring crawl4ai or Playwright. Set config.toml [fetch] reddit_user_agent to
override the default UA — Reddit's API rules say the UA should identify the bot.

Reddit may answer with a login wall instead: a redirect to /login (e.g.
`?reason=lor2`) that serves a 200 "Welcome to Reddit" page, for HTML and `.rss`
alike. That is reported as a failure, never as fetched content.
'''

import asyncio
import re
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx

from anya.config import get_config
from anya.fetchers._cache import cached_client
from anya.fetchers._html import clean_html, html2markdown
from anya.fetchers.protocol import FetchResult, WebFetcher
from anya.fetchers.rss import _parse_bytes as _parse_feed

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


def _login_wall(final_url: httpx.URL | str) -> str | None:
    '''
    If a response's final URL (after redirects) is Reddit's login page, describe
    the wall; otherwise None.
    '''
    parsed = urlparse(str(final_url))
    if not (parsed.hostname or '').endswith('reddit.com') or not parsed.path.startswith('/login'):
        return None
    reason = parse_qs(parsed.query).get('reason', [''])[0]
    return f'Reddit login wall (redirected to /login{f", reason={reason}" if reason else ""})'


class RedditFetcher(WebFetcher):
    '''Reddit-aware fetcher: old.reddit.com with UA → RSS fallback.'''

    def __init__(self, user_agent: str | None = None, timeout: float = 30.0,
                 drop_tabindex_minus_one: bool = False):
        self.user_agent = user_agent or get_config().fetch.reddit_user_agent
        self.timeout = timeout
        self.drop_tabindex_minus_one = drop_tabindex_minus_one

    async def fetch(self, url: str) -> FetchResult:
        old_url = _to_old_reddit(url)
        rss_url = _to_rss(url)
        async with cached_client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={'User-Agent': self.user_agent},
        ) as client:
            try:
                resp = await client.get(old_url)
                if wall := _login_wall(resp.url):
                    fallback_reason = wall
                elif resp.is_success:
                    html = resp.content.decode(resp.encoding or 'utf-8', errors='replace')
                    tree, _ = clean_html(html, drop_tabindex_minus_one=self.drop_tabindex_minus_one)
                    title_elem = tree.css_first('title')
                    return FetchResult(
                        url=old_url,
                        markdown=html2markdown(tree),
                        title=title_elem.text(strip=True) if title_elem else None,
                        success=True,
                    )
                else:
                    fallback_reason = f'old.reddit.com returned HTTP {resp.status_code}'
            except Exception as e:  # noqa: BLE001
                fallback_reason = f'old.reddit.com fetch failed: {e}'

            # RSS fallback.
            try:
                resp = await client.get(rss_url)
                if wall := _login_wall(resp.url):
                    raise RuntimeError(wall)
                resp.raise_for_status()
                markdown, feed_title = await asyncio.to_thread(_parse_feed, resp.content, rss_url)
            except Exception as e:  # noqa: BLE001
                return FetchResult(
                    url=url,
                    markdown='',
                    success=False,
                    error=f'{fallback_reason}; RSS fallback ({rss_url}) failed: {e}',
                )
        return FetchResult(url=rss_url, markdown=markdown, title=feed_title, success=True)
