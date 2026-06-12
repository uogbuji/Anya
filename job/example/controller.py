'''
Example controller: fetch a couple of pages, ask the LLM to summarize them.

Anya runs this as a subprocess. Stdout becomes the job report. Treat any
text the LLM returns as untrusted input — never feed it back to a shell, an
eval, or a path constructor.
'''

import asyncio

from anya import inference
from anya.fetchers import fetch_url


URLS = [
    'https://example.com',
    'https://old.reddit.com/r/LocalLLaMA/',
]


async def gather() -> str:
    '''Fetch each URL; build a single Markdown blob for the LLM.'''
    parts: list[str] = []
    for url in URLS:
        result = await fetch_url(url)
        if result.success:
            header = f'# Fetched: {result.url}'
            if result.title:
                header += f'\nTitle: {result.title}'
            parts.append(f'{header}\n\n{result.markdown[:2000]}')
        else:
            parts.append(f'# Fetch failed: {url}\n{result.error}')
    return '\n\n---\n\n'.join(parts) if parts else '(no data)'


async def main() -> None:
    data = await gather()
    report = await inference('summarize', context={'data': data})
    print(report)


if __name__ == '__main__':
    asyncio.run(main())
