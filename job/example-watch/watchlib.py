'''
Pure helpers for the example-watch job: no network, no LLM, no clock. Kept apart
from controller.py so they can be tested directly (see test_watchlib.py, run with `anya test`).

State file layout (state.json in the job dir):

    {"pages": {"<url>": {"digest": "<sha256>", "excerpt": "<first N chars>", "changed": "YYYY-MM-DD"}}}
'''

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

EXCERPT_CHARS = 3000  # how much of each page the LLM sees (before and after)


@dataclass(frozen=True)
class Change:
    url: str
    before: str  # excerpt from the last run
    after: str   # excerpt from this run


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_state(path: Path) -> dict:
    '''Read the job's state; a missing or unreadable file means a fresh start.'''
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'pages': {}}
    return state if isinstance(state.get('pages'), dict) else {'pages': {}}


def save_state(path: Path, state: dict) -> None:
    '''Write state atomically (temp file + rename), so an interrupted run can't corrupt it.'''
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def plan(fetched: dict[str, str | None], state: dict) -> tuple[list[Change], list[str], list[str]]:
    '''
    Compare this run's pages (url → markdown, or None if the fetch failed) with state.
    Returns (changes, new_urls, failed_urls). A page seen for the first time is a
    baseline, not a change: there's nothing to compare it with yet.
    '''
    changes, new, failed = [], [], []
    for url, markdown in fetched.items():
        if markdown is None:
            failed.append(url)
            continue
        prev = state['pages'].get(url)
        if prev is None:
            new.append(url)
        elif prev.get('digest') != digest(markdown):
            changes.append(Change(url, prev.get('excerpt', ''), markdown[:EXCERPT_CHARS]))
    return changes, new, failed


def next_state(state: dict, fetched: dict[str, str | None], today: str) -> dict:
    '''State after this run: record each successfully fetched page's digest and excerpt.'''
    pages = dict(state['pages'])
    for url, markdown in fetched.items():
        if markdown is None:
            continue  # keep the old entry, so the next successful fetch compares against it
        d = digest(markdown)
        if pages.get(url, {}).get('digest') != d:
            pages[url] = {'digest': d, 'excerpt': markdown[:EXCERPT_CHARS], 'changed': today}
    return {'pages': pages}


def allowed_highlights(highlights: object, allowed_urls: set[str]) -> list[dict]:
    '''
    Keep only well-formed highlights whose URL is one we actually fetched and flagged.
    LLM output is untrusted input: a schema constrains its shape, and this check
    constrains its content to an allow-list built from our own data.
    '''
    if not isinstance(highlights, list):
        return []
    return [h for h in highlights
            if isinstance(h, dict) and h.get('url') in allowed_urls and isinstance(h.get('note'), str)]
