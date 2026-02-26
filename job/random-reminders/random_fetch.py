'''
Fetch a random set of web pages from the list in candidates.txt.
Runs before Claude is called. Output goes to context.
'''

import asyncio
import os
import random
from pathlib import Path

from anya.fetchers import create_fetcher


# Job env is set by executor; ANYA_JOB_ID, ANYA_JOB_PATH, ANYA_JOB_SELECT available
job_id = os.environ.get('ANYA_JOB_ID', 'unknown')
job_path = Path(os.environ.get('ANYA_JOB_PATH', '.'))
n_select = int(os.environ.get('ANYA_JOB_SELECT', '3'))


async def _run():
    '''
    Pull lines in candidates.txt, select n_select random ones (taking weighting into account),
    and fetch the web content as markdown, and print the output for context, headlined with the context field.

    candidates.txt format: Weight|URL|context|Method (optional)
    Method: plain (default) or crawl4ai
    '''
    candidates_file = job_path / 'candidates.txt'
    with open(candidates_file, 'r') as f:
        lines = f.readlines()
    lines = [line.strip() for line in lines if not line.startswith('#')]
    parsed = []
    for line in lines:
        parts = line.split('|')
        weight = int(parts[0])
        url = parts[1]
        context = parts[2]
        method = (parts[3].strip().lower() if len(parts) > 3 else 'plain') or 'plain'
        parsed.append((weight, url, context, method))
    lines = random.choices(parsed, weights=[p[0] for p in parsed], k=n_select)
    for weight, url, context, method in lines:
        fetcher = create_fetcher(method)
        result = await fetcher.fetch(url)
        if result.success:
            print(f'# Fetched: {result.url}')
            if result.title:
                print(f'Title: {result.title}')
            print(result.markdown[:2000])  # Truncate for context
        else:
            print(f'# Fetch failed: {result.error}')


asyncio.run(_run())
