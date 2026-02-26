'''
Example fetch script. Runs before Claude is called. Output goes to context.
Read-only: no destructive actions.
'''

import asyncio
import os

from anya.fetchers import fetch_url

# Job env is set by executor; ANYA_JOB_ID, ANYA_JOB_PATH available
job_id = os.environ.get('ANYA_JOB_ID', 'unknown')


async def _run():
    result = await fetch_url('https://example.com')
    if result.success:
        print(f'# Fetched: {result.url}')
        if result.title:
            print(f'Title: {result.title}')
        print(result.markdown[:2000])  # Truncate for context
    else:
        print(f'# Fetch failed: {result.error}')


asyncio.run(_run())
