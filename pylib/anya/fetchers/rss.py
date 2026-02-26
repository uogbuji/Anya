'''RSS fetcher using feedparser.'''

import feedparser


async def fetch_rss(url: str) -> str:
    '''
    Fetch RSS/Atom feed and return a readable text summary. Read-only.
    '''
    import asyncio
    # feedparser is sync; run in executor to avoid blocking
    def _parse():
        feed = feedparser.parse(url)
        lines = [f'# {feed.feed.get("title", "Feed")}']
        for entry in feed.entries[:20]:
            title = entry.get('title', '')
            link = entry.get('link', '')
            summary = entry.get('summary', '')[:500]
            lines.append(f'\n## {title}\n{link}\n{summary}')
        return '\n'.join(lines)
    return await asyncio.to_thread(_parse)
