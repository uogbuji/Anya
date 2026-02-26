'''
Actions register: inline actions in MAIN.md that expand to results.

Example in MAIN.md:
---ACTION---
fetch('https://old.reddit.com/r/LocalLLaMA/')
---END ACTION---

Gets replaced with:
---ACTION RESULT---
[Page content in Markdown]
'''

import re
from collections.abc import Awaitable, Callable

from anya.fetchers import fetch_url


async def _action_fetch(url: str) -> str:
    '''Fetch URL and return markdown.'''
    result = await fetch_url(url)
    if result.success:
        return result.markdown
    return f'(fetch failed: {result.error})'


# Action name -> async handler (*args) -> str
ACTION_HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    'fetch': _action_fetch,
}


def _parse_action(content: str) -> tuple[str | None, list]:
    '''
    Parse action content. Returns (action_name, args) or (None, []).

    Supported: fetch('url') or fetch("url")
    '''
    content = content.strip()
    m = re.match(r"fetch\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content)
    if m:
        return ('fetch', [m.group(1)])
    return (None, [])


async def execute_action(content: str) -> str:
    '''Execute a single action and return its result string.'''
    name, args = _parse_action(content)
    if name and name in ACTION_HANDLERS:
        return await ACTION_HANDLERS[name](*args)
    return f'(unknown action: {content!r})'


ACTION_BLOCK_PATTERN = re.compile(
    r'---ACTION---\s*(.*?)\s*---END ACTION---',
    re.DOTALL,
)


async def expand_actions(main_md: str) -> str:
    '''
    Replace ---ACTION---...---END ACTION--- blocks with ---ACTION RESULT--- content.

    Each block is executed and replaced by the fetched/result markdown.
    '''
    parts: list[str] = []
    last_end = 0

    for m in ACTION_BLOCK_PATTERN.finditer(main_md):
        parts.append(main_md[last_end : m.start()])
        content = m.group(1).strip()
        result = await execute_action(content)
        parts.append(f'---ACTION RESULT---\n{result}\n')
        last_end = m.end()

    parts.append(main_md[last_end:])
    return ''.join(parts)
