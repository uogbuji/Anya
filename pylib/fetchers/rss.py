'''RSS/Atom fetcher using feedparser.

`fetch_rss(url)` returns a markdown string (used by the Reddit fallback path).
`RSSFetcher` wraps that for the WebFetcher protocol — registered as 'rss' in
create_fetcher.
'''

from __future__ import annotations

import asyncio
import html as _html
import re

import feedparser
import structlog

from anya.fetchers._cache import cached_client
from anya.fetchers.protocol import FetchResult, WebFetcher


logger = structlog.get_logger()


_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _strip_html(s: str) -> str:
    if not s:
        return ''
    s = _html.unescape(s)
    s = _TAG_RE.sub('', s)
    return _WS_RE.sub(' ', s).strip()


def _entry_summary(entry, limit: int = 500) -> str:
    summary = entry.get('summary', '') or ''
    if not summary and entry.get('content'):
        content = entry['content']
        if isinstance(content, list) and content:
            summary = content[0].get('value', '') or ''
        elif isinstance(content, str):
            summary = content
    summary = _strip_html(summary)
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + '…'
    return summary


def _parse_bytes(content: bytes, source_url: str, max_entries: int = 20) -> tuple[str, str | None]:
    '''Parse feed bytes and return (markdown, feed_title).'''
    parsed = feedparser.parse(content)
    if parsed.bozo:
        logger.debug('rss bozo flag set', url=source_url, exc=str(parsed.get('bozo_exception', '')))
    feed_title = (parsed.feed.get('title') if hasattr(parsed, 'feed') else None) or None
    lines = [f'# {feed_title or "Feed"}']
    for entry in (parsed.entries or [])[:max_entries]:
        title = entry.get('title', '') or '(untitled)'
        link = entry.get('link', '') or ''
        summary = _entry_summary(entry)
        block = [f'\n## {title}']
        if link:
            block.append(link)
        if summary:
            block.append(summary)
        lines.append('\n'.join(block))
    return '\n'.join(lines), feed_title


async def fetch_rss(url: str, *, timeout: float = 15.0, max_entries: int = 20) -> str:
    '''Fetch an RSS/Atom feed and return a readable markdown summary.'''
    async with cached_client(follow_redirects=True, timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    markdown, _ = await asyncio.to_thread(_parse_bytes, resp.content, url, max_entries)
    return markdown


class RSSFetcher(WebFetcher):
    '''RSS/Atom fetcher returning a FetchResult.'''

    def __init__(self, timeout: float = 15.0, max_entries: int = 20):
        self.timeout = timeout
        self.max_entries = max_entries

    async def fetch(self, url: str) -> FetchResult:
        try:
            async with cached_client(follow_redirects=True, timeout=self.timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            return FetchResult(url=url, markdown='', success=False, error=f'RSS fetch failed: {e}')
        try:
            markdown, feed_title = await asyncio.to_thread(_parse_bytes, resp.content, url, self.max_entries)
        except Exception as e:  # noqa: BLE001
            return FetchResult(url=url, markdown='', success=False, error=f'RSS parse failed: {e}')
        return FetchResult(url=url, markdown=markdown, title=feed_title, success=True)
