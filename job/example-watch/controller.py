'''
Example controller: watch a few pages and report the significant changes.

A reference for common job patterns:
- Per-job state: state.json lives in this job's own dir (ANYA_JOB_PATH), so it persists
  across runs (and, under Docker, across restarts, since the job dir is a mounted volume).
- Fan-out filtering: one small structured question per changed page, on a cheap model,
  then one synthesis call, on a stronger model, over only the pages that passed.
- Structured output: response_schema makes inference() return a dict.
- Untrusted LLM output: the report's URLs are checked against the pages we flagged.

Anya runs this as a subprocess; stdout is the job report. Pure logic is in watchlib.py.
'''

import asyncio
import os
from datetime import date
from pathlib import Path

from anya import inference
from anya.fetchers import fetch_url

from watchlib import allowed_highlights, load_state, next_state, plan, save_state

PAGES = [
    'https://example.com',
    'https://www.python.org/downloads/',
    'https://peps.python.org/',
]
STATE_FILE = Path(os.environ.get('ANYA_JOB_PATH', Path(__file__).parent)) / 'state.json'

# Model aliases from config.toml. None means the configured default; in a real job, point
# the filter at a cheap alias (e.g. 'fast') and the report at a stronger one.
FILTER_MODEL = None
REPORT_MODEL = None

# Both schemas meet OpenAI's strict-mode rules (all properties required, no extras).
SIGNIFICANCE_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['significant', 'reason'],
    'properties': {'significant': {'type': 'boolean'}, 'reason': {'type': 'string'}},
}
REPORT_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['highlights'],
    'properties': {'highlights': {'type': 'array', 'items': {
        'type': 'object',
        'additionalProperties': False,
        'required': ['url', 'note'],
        'properties': {'url': {'type': 'string'}, 'note': {'type': 'string'}},
    }}},
}


async def main() -> None:
    state = load_state(STATE_FILE)
    fetched: dict[str, str | None] = {}
    for url in PAGES:
        result = await fetch_url(url)
        fetched[url] = result.markdown if result.success else None

    changes, new, failed = plan(fetched, state)

    # Fan-out: a cheap yes/no per changed page.
    flagged = []
    for change in changes:
        verdict = await inference('significance-filter', model=FILTER_MODEL, response_schema=SIGNIFICANCE_SCHEMA,
                                  context={'url': change.url, 'before': change.before, 'after': change.after})
        if verdict.get('significant') is True:
            flagged.append((change, str(verdict.get('reason', ''))))

    # Synthesis over the survivors only.
    lines = []
    if flagged:
        blocks = '\n\n'.join(f'## {c.url}\nWhy it was flagged: {reason}\n\n### Before\n{c.before}\n\n### After\n{c.after}'
                             for c, reason in flagged)
        report = await inference('change-report', model=REPORT_MODEL, response_schema=REPORT_SCHEMA,
                                 context={'changes': blocks})
        for h in allowed_highlights(report.get('highlights'), {c.url for c, _ in flagged}):
            lines.append(f'- {h["url"]}: {h["note"]}')

    print(f'Watched {len(PAGES)} pages: {len(changes)} changed, {len(flagged)} significant.')
    print('\n'.join(lines) if lines else 'No significant changes.')
    if new:
        print(f'Now watching (baseline recorded): {", ".join(new)}')
    if failed:
        print(f'Could not fetch: {", ".join(failed)}')

    # Save state last: if anything above raised, the next run compares against the same
    # baseline and reconsiders the same changes.
    save_state(STATE_FILE, next_state(state, fetched, date.today().isoformat()))


if __name__ == '__main__':
    asyncio.run(main())
